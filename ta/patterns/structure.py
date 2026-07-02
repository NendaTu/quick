"""
Market Structure Strategy: BOS, MSS, and CHOCH

How it works:
1. This strategy tracks "Market Structure" by identifying when the price breaks
   through previous Higher Highs or Lower Lows.
2. Break of Structure (BOS): Occurs when price continues the current trend
   (e.g., breaking a previous ceiling in an uptrend).
3. Market Structure Shift (MSS): Occurs when price impulsively breaks the opposite
   side of the trend, signaling a potential reversal.
4. Signals:
   - Bullish: When a candle closes above a confirmed Swing High.
   - Bearish: When a candle closes below a confirmed Swing Low.
5. Stop Loss (SL): Placed 1 tick beyond the level that was just broken, ensuring
   capital is protected if the breakout fails.
6. Take Profit (TP): Targets a specific net profit (default +1% ROE).
7. Backtesting command: `python backtest.py structure [type] [rrr_override]`
   - [type]: 'bos', 'mss', or 'all' (Default).
"""

from typing import List, Dict, Optional
from ta.patterns.swings import detect_swings
from ta.indicators.atr import compute_atr
from tools.trading_utils import calculate_tp_for_roe, calculate_target_roe_for_rrr
import config

# --- Configuration ---
# Toggle to enable/disable structural analysis.
ENABLED = True

# Break candle range must be > IMPULSE_THRESHOLD * ATR to confirm MSS vs CHOCH.
IMPULSE_THRESHOLD = 1.5

# Minimum distance (%) between swings to filter out market noise.
MIN_SWING_DIST_PCT = 0.002

# If True, requires the candle to CLOSE beyond the high/low for a valid break.
# Reduces false breakouts on wicks.
CONFIRM_BREAK_ON_CLOSE = True

# Default Strategy Settings
DEFAULT_TARGET_ROE = 0.01
SL_TICK_BUFFER = 0.0001

def get_signal(ohlcv, tf, params=None, **kwargs) -> Optional[Dict]:
    """
    Backtesting entry point for Market Structure strategy.
    """
    if len(ohlcv) < 51:
        return None

    # Parse Parameters
    type_req = params[0].lower() if params and len(params) > 0 else 'all'
    rrr_override = float(params[1]) if params and len(params) > 1 else None

    # 1. Gather Structure Info
    struct = identify_structure(ohlcv)
    sig = struct.get('structure_signal')
    if not sig:
        return None

    # Filter by type
    if type_req != 'all' and type_req not in sig:
        return None

    side = 'buy' if 'bullish' in sig else 'sell'
    entry = ohlcv[-1]['c']

    # 2. SL: 1 tick beyond the level that was broken
    if side == 'buy':
        stop = struct['last_hh'] * (1 - SL_TICK_BUFFER)
    else: # sell
        stop = struct['last_ll'] * (1 + SL_TICK_BUFFER)

    if stop == entry: return None

    # 3. Calculate TP
    entry_maker = (config.ENTRY_ORDER_TYPE == "limit")
    tp_maker = (config.TP_ORDER_TYPE == "limit")

    if rrr_override is not None:
        target_roe = calculate_target_roe_for_rrr(rrr_override, entry, stop, 20, entry_maker=entry_maker)
    else:
        target_roe = DEFAULT_TARGET_ROE

    tp = calculate_tp_for_roe(entry, target_roe, side, 20, entry_maker=entry_maker, exit_maker=tp_maker)

    return {
        "side": side,
        "entry_price": entry,
        "stop_price": stop,
        "exit_price": tp,
        "metadata": {"type": sig, "target_roe": target_roe}
    }

def identify_structure(ohlcv: List[dict]) -> Dict:
    """
    Analyzes market structure and identifies breaks.
    Uses closed candles for structural points to prevent repainting.
    """
    if not ENABLED or len(ohlcv) < 51:
        return {}

    # 1. Get confirmed swing points from CLOSED candles
    closed_ohlcv = ohlcv[:-1]
    swings = detect_swings(closed_ohlcv, strength=2)
    highs = swings['highs']
    lows = swings['lows']

    if len(highs) < 2 or len(lows) < 2:
        return {}

    # Last trend-following extremes
    last_hh = highs[-1]['price']
    last_ll = lows[-1]['price']

    last_confirmed_high = highs[-1]
    last_confirmed_low = lows[-1]

    curr = ohlcv[-1] # Check break against live candle
    atr = compute_atr([c['h'] for c in closed_ohlcv], [c['l'] for c in closed_ohlcv], [c['c'] for c in closed_ohlcv])

    structure_signal = None

    # --- BREAK DETECTION ---
    is_breaking_hh = (curr['c'] > last_hh) if CONFIRM_BREAK_ON_CLOSE else (curr['h'] > last_hh)
    is_breaking_lh = (curr['c'] > last_confirmed_high['price']) if CONFIRM_BREAK_ON_CLOSE else (curr['h'] > last_confirmed_high['price'])
    is_breaking_ll = (curr['c'] < last_ll) if CONFIRM_BREAK_ON_CLOSE else (curr['l'] < last_ll)
    is_breaking_hl = (curr['c'] < last_confirmed_low['price']) if CONFIRM_BREAK_ON_CLOSE else (curr['l'] < last_confirmed_low['price'])

    if is_breaking_hh:
        structure_signal = 'bullish_bos'
    elif is_breaking_lh:
        candle_range = curr['h'] - curr['l']
        if candle_range > IMPULSE_THRESHOLD * atr:
            structure_signal = 'bullish_mss'
        else:
            structure_signal = 'bullish_choch'
    elif is_breaking_ll:
        structure_signal = 'bearish_bos'
    elif is_breaking_hl:
        candle_range = curr['h'] - curr['l']
        if candle_range > IMPULSE_THRESHOLD * atr:
            structure_signal = 'bearish_mss'
        else:
            structure_signal = 'bearish_choch'

    return {
        'structure_signal': structure_signal,
        'last_hh': last_hh,
        'last_ll': last_ll
    }
