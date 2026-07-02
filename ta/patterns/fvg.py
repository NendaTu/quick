"""
Fair Value Gap (FVG) Recognition Module

A Fair Value Gap occurs in a three-candle sequence when there is a lack of price overlap between
the wick of the first candle and the wick of the third candle.
"""

"""
Fair Value Gap (FVG) Recognition Module

How it works:
1. A Fair Value Gap (FVG) is a three-candle sequence where price moves so quickly that a "gap"
   is left between the first candle's wick and the third candle's wick.
2. This module provides both real-time detection and a backtesting strategy.
3. FVG Backtesting Strategy (`python backtest.py fvg [dir_count] [gap_pct] [rrr_override]`):
   - [dir_count]: How many of the 3 candles must match the FVG's direction (1, 2, or 3). Default is 3.
   - [gap_pct]: Minimum percentage of the 2nd candle's range that the gap must cover (e.g., 30%).
   - [rrr_override]: Optional Reward-to-Risk Ratio (e.g., 1.5). If not provided, targets a net +1% ROE.
4. Logic:
   - Entry: Occurs at the close of the 3rd candle in the sequence.
   - Stop Loss (SL): Placed 1 tick shy of the gap's midpoint on the opposite side.
   - Take Profit (TP): Targets either a fixed net profit or a specific RRR.
"""

from typing import List, Dict, Optional
from tools.trading_utils import calculate_tp_for_roe, calculate_target_roe_for_rrr
import config

# --- Configuration ---
# Toggle to enable/disable FVG detection.
ENABLED = True

# Number of candles to scan for active (unfilled) gaps.
HISTORY_DEPTH = 50

# Timeframe used for FVG detection (e.g., '5m' for HTF confluence).
TIMEFRAME = "5m"

# Default Strategy Settings
DEFAULT_DIR_COUNT = 3
DEFAULT_GAP_PCT = 30.0
DEFAULT_TARGET_ROE = 0.01
SL_TICK_BUFFER = 0.0001

def get_signal(ohlcv, tf, params=None, **kwargs) -> Optional[Dict]:
    """
    Backtesting entry point for FVG strategy.
    """
    if len(ohlcv) < 3:
        return None

    # Parse Parameters
    dir_count_req = int(params[0]) if params and len(params) > 0 else DEFAULT_DIR_COUNT
    gap_pct_req = float(params[1]) if params and len(params) > 1 else DEFAULT_GAP_PCT
    rrr_override = float(params[2]) if params and len(params) > 2 else None

    # The 3-candle sequence is the last three closed candles
    c1, c2, c3 = ohlcv[-3], ohlcv[-2], ohlcv[-1]

    # 1. Detect FVG type and price levels
    fvg_type = None
    gap_top, gap_bottom = 0, 0

    if c3['l'] > c1['h']:
        fvg_type = "buy" # Bullish
        gap_top, gap_bottom = c3['l'], c1['h']
    elif c1['l'] > c3['h']:
        fvg_type = "sell" # Bearish
        gap_top, gap_bottom = c1['l'], c3['h']

    if not fvg_type:
        return None

    # 2. Requirement A: Direction Count
    match_count = 0
    for c in [c1, c2, c3]:
        if fvg_type == "buy" and c['c'] > c['o']: match_count += 1
        elif fvg_type == "sell" and c['c'] < c['o']: match_count += 1

    if match_count < dir_count_req:
        return None

    # 3. Requirement B: Gap Percentage of C2
    c2_range = c2['h'] - c2['l']
    if c2_range <= 0: return None

    gap_size = gap_top - gap_bottom
    actual_gap_pct = (gap_size / c2_range) * 100

    if actual_gap_pct < gap_pct_req:
        return None

    # 4. Entry/Exit Calculations
    entry = c3['c'] # Close of 3rd candle
    gap_mid = (gap_top + gap_bottom) / 2

    # SL: 1 tick shy of gap midpoint on opposite side
    if fvg_type == "buy":
        stop = gap_mid * (1 - SL_TICK_BUFFER)
    else:
        stop = gap_mid * (1 + SL_TICK_BUFFER)

    # TP: ROI or RRR
    entry_maker = (config.ENTRY_ORDER_TYPE == "limit")
    tp_maker = (config.TP_ORDER_TYPE == "limit")

    if rrr_override is not None:
        target_roe = calculate_target_roe_for_rrr(
            rrr_override, entry, stop, 20,
            entry_maker=entry_maker,
            exit_maker=False # SL is usually Taker
        )
    else:
        target_roe = DEFAULT_TARGET_ROE

    tp = calculate_tp_for_roe(
        entry, target_roe, fvg_type, 20,
        entry_maker=entry_maker,
        exit_maker=tp_maker
    )

    return {
        "side": fvg_type,
        "entry_price": entry,
        "stop_price": stop,
        "exit_price": tp,
        "metadata": {
            "match_count": match_count,
            "gap_pct": actual_gap_pct,
            "target_roe": target_roe
        }
    }

def detect_fvgs(ohlcv: List[dict], depth: int = None) -> Dict:
    """
    Analyzes the provided OHLCV data for Fair Value Gaps.
    Only considers CLOSED candles to prevent repainting.
    """
    if depth is None:
        depth = HISTORY_DEPTH

    if not ENABLED or len(ohlcv) < 4: # Need 3 closed + 1 live
        return {}

    # Slice to exclude the live (developing) candle to ensure signals are stable
    closed_ohlcv = ohlcv[:-1]

    # Slice to relevant history
    scan_start = max(0, len(closed_ohlcv) - depth)
    relevant_candles = closed_ohlcv[scan_start:]

    fvgs = []

    # 1. Identify all gaps in the sequence
    for i in range(1, len(relevant_candles) - 1):
        c1 = relevant_candles[i-1]
        c2 = relevant_candles[i]
        c3 = relevant_candles[i+1]

        # Bullish FVG (Gap up: C1 High < C3 Low)
        if c3['l'] > c1['h']:
            fvgs.append({
                'type': 'bullish',
                'top': c3['l'],
                'bottom': c1['h'],
                'index': i + scan_start,
                'state': 'unfilled'
            })

        # Bearish FVG (Gap down: C1 Low > C3 High)
        elif c1['l'] > c3['h']:
            fvgs.append({
                'type': 'bearish',
                'top': c1['l'],
                'bottom': c3['h'],
                'index': i + scan_start,
                'state': 'unfilled'
            })

    if not fvgs:
        return {'fvg_count': 0, 'nearest_fvg': None}

    # 2. Update states based on subsequent price action (including the live candle for fill)
    current_price = ohlcv[-1]['c']

    for fvg in fvgs:
        # Check action from the candle AFTER the gap (index + 2) to current live candle
        post_gap_start = fvg['index'] + 2
        post_gap_candles = ohlcv[post_gap_start:]

        for pc in post_gap_candles:
            high = pc['h']
            low = pc['l']
            close = pc['c']

            # Mitigation/Engagement check
            touches = (high >= fvg['bottom'] and low <= fvg['top'])
            closes_inside = (close >= fvg['bottom'] and close <= fvg['top'])

            if fvg['type'] == 'bullish':
                # If price falls fully below the gap, it becomes Inverted
                if close < fvg['bottom']:
                    fvg['state'] = 'inverted'
                    break
                elif closes_inside:
                    fvg['state'] = 'engaged'
                elif touches and fvg['state'] == 'unfilled':
                    fvg['state'] = 'mitigated'
            else: # bearish
                # If price rises fully above the gap, it becomes Inverted
                if close > fvg['top']:
                    fvg['state'] = 'inverted'
                    break
                elif closes_inside:
                    fvg['state'] = 'engaged'
                elif touches and fvg['state'] == 'unfilled':
                    fvg['state'] = 'mitigated'

    # 3. Find the nearest active (not yet fully filled/inverted) FVG
    active_fvgs = [f for f in fvgs if f['state'] != 'inverted']

    nearest = None
    if active_fvgs:
        def get_dist(f):
            mid = (f['top'] + f['bottom']) / 2
            return abs(current_price - mid)
        nearest = min(active_fvgs, key=get_dist)

    return {
        'fvg_count': len(active_fvgs),
        'nearest_fvg_type': nearest['type'] if nearest else None,
        'nearest_fvg_dist': (current_price / ((nearest['top'] + nearest['bottom']) / 2) - 1) if nearest else 0,
        'nearest_fvg_state': nearest['state'] if nearest else None
    }
