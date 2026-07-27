"""
1. Summary: Fair Value Gap (FVG) stateless recognition module.
2. Description: Spots imbalances across 3-candle structures where price delivered too rapidly, leaving a gap between wicks.
3. Context: Used to map liquidity vacuums and draw-on-liquidity zones.
"""
from typing import List, Dict, Optional
from tools.trading_utils import calculate_tp_for_roe, calculate_target_roe_for_rrr
import config

# --- Configuration ---
ENABLED = True
HISTORY_DEPTH = 50
TIMEFRAME = "5m"

# Default Strategy Settings
DEFAULT_DIR_COUNT = 3
DEFAULT_GAP_PCT = 30.0
DEFAULT_TARGET_ROE = 0.01
SL_TICK_BUFFER = 0.0001

def get_signal(ohlcv, tf, params=None, **kwargs) -> Optional[Dict]:
    # [REPAIR-20260708] Use only CLOSED candles to prevent look-ahead/repainting bias
    closed_ohlcv = ohlcv[:-1]
    if len(closed_ohlcv) < 3:
        return None

    dir_count_req = int(params[0]) if params and len(params) > 0 else DEFAULT_DIR_COUNT
    gap_pct_req = float(params[1]) if params and len(params) > 1 else DEFAULT_GAP_PCT
    rrr_override = float(params[2]) if params and len(params) > 2 else None

    c1, c2, c3 = closed_ohlcv[-3], closed_ohlcv[-2], closed_ohlcv[-1]

    fvg_type = None
    gap_top, gap_bottom = 0, 0

    if c3['l'] > c1['h']:
        # Bullish: C2 strictly contained
        if c2['h'] < c3['h'] and c2['l'] > c1['l']:
            fvg_type = "buy"
            gap_top, gap_bottom = c3['l'], c1['h']
    elif c1['l'] > c3['h']:
        # Bearish: C2 strictly contained
        if c2['l'] > c3['l'] and c2['h'] < c1['h']:
            fvg_type = "sell"
            gap_top, gap_bottom = c1['l'], c3['h']

    if not fvg_type:
        return None

    # Requirement A: Direction Count
    match_count = 0
    for c in [c1, c2, c3]:
        if fvg_type == "buy" and c['c'] > c['o']: match_count += 1
        elif fvg_type == "sell" and c['c'] < c['o']: match_count += 1

    if match_count < dir_count_req:
        return None

    # Requirement B: Gap Percentage
    c2_range = c2['h'] - c2['l']
    if c2_range <= 0: return None

    gap_size = gap_top - gap_bottom
    actual_gap_pct = (gap_size / c2_range) * 100

    if actual_gap_pct < gap_pct_req:
        return None

    entry = c3['c']
    gap_mid = (gap_top + gap_bottom) / 2

    if fvg_type == "buy":
        stop = gap_mid * (1 - SL_TICK_BUFFER)
    else:
        stop = gap_mid * (1 + SL_TICK_BUFFER)

    entry_maker = (config.ENTRY_ORDER_TYPE == "limit")
    tp_maker = (config.TP_ORDER_TYPE == "limit")

    if rrr_override is not None:
        target_roe = calculate_target_roe_for_rrr(rrr_override, entry, stop, 20, entry_maker=entry_maker)
    else:
        target_roe = DEFAULT_TARGET_ROE

    tp = calculate_tp_for_roe(entry, target_roe, fvg_type, 20, entry_maker=entry_maker, exit_maker=tp_maker)

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
    if depth is None:
        depth = HISTORY_DEPTH

    if not ENABLED or len(ohlcv) < 4:
        return {}

    closed_ohlcv = ohlcv[:-1]
    scan_start = max(0, len(closed_ohlcv) - depth)
    relevant_candles = closed_ohlcv[scan_start:]

    fvgs = []

    for i in range(1, len(relevant_candles) - 1):
        c1 = relevant_candles[i-1]
        c2 = relevant_candles[i]
        c3 = relevant_candles[i+1]

        if c3['l'] > c1['h']:
            # [HARDENING] Strict containment
            if c2['h'] < c3['h'] and c2['l'] > c1['l']:
                fvgs.append({
                    'type': 'bullish',
                    'top': c3['l'],
                    'bottom': c1['h'],
                    'index': i + scan_start,
                    'state': 'unfilled'
                })
        elif c1['l'] > c3['h']:
            # [HARDENING] Strict containment
            if c2['l'] > c3['l'] and c2['h'] < c1['h']:
                fvgs.append({
                    'type': 'bearish',
                    'top': c1['l'],
                    'bottom': c3['h'],
                    'index': i + scan_start,
                    'state': 'unfilled'
                })

    if not fvgs:
        return {'fvg_count': 0, 'nearest_fvg': None}

    current_price = ohlcv[-1]['c']

    for fvg in fvgs:
        post_gap_start = fvg['index'] + 2
        post_gap_candles = ohlcv[post_gap_start:]

        for pc in post_gap_candles:
            high, low, close = pc['h'], pc['l'], pc['c']
            touches = (high >= fvg['bottom'] and low <= fvg['top'])
            closes_inside = (close >= fvg['bottom'] and close <= fvg['top'])

            if fvg['type'] == 'bullish':
                if close < fvg['bottom']:
                    fvg['state'] = 'inverted'
                    break
                elif closes_inside:
                    fvg['state'] = 'engaged'
                elif touches and fvg['state'] == 'unfilled':
                    fvg['state'] = 'mitigated'
            else:
                if close > fvg['top']:
                    fvg['state'] = 'inverted'
                    break
                elif closes_inside:
                    fvg['state'] = 'engaged'
                elif touches and fvg['state'] == 'unfilled':
                    fvg['state'] = 'mitigated'

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
        'nearest_fvg_state': nearest['state'] if nearest else None,
        'nearest_fvg_top': nearest['top'] if nearest else None,
        'nearest_fvg_bottom': nearest['bottom'] if nearest else None
    }
