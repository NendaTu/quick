"""
Market Structure Module: BOS, MSS, and CHOCH

Tracks structural breaks to signal trend continuation or reversal.
"""

from typing import List, Dict, Optional
from ta.patterns.swings import detect_swings
from ta.indicators.atr import compute_atr

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
