"""
Market Structure Module: BOS, MSS, and CHOCH

Tracks structural breaks to signal trend continuation or reversal.

Patterns:
1. Break of Structure (BOS): Violates last HH (uptrend) or LL (downtrend). Confirms continuation.
2. Market Structure Shift (MSS): Violates last HL (uptrend) or LH (downtrend). Signals potential reversal.
3. Change of Character (CHOCH): MSS-like break but lacking impulsive follow-through. Warning signal.

Distinction:
- BOS breaks the trend-following extreme.
- MSS/CHOCH breaks the counter-trend pivot.
"""

from typing import List, Dict, Optional
from ta.patterns.swings import detect_swings
from ta.indicators.atr import compute_atr

# --- Internal Configuration ---
ENABLED = True
IMPULSE_THRESHOLD = 1.5 # Break candle range > 1.5x ATR confirms MSS vs CHOCH
MIN_SWING_DIST_PCT = 0.002 # 0.2% distance between swings to avoid noise
CONFIRM_BREAK_ON_CLOSE = True # If True, requires C > High for BOS/MSS

def identify_structure(ohlcv: List[dict]) -> Dict:
    """
    Analyzes market structure and identifies breaks.
    """
    if not ENABLED or len(ohlcv) < 50:
        return {}

    # 1. Get confirmed swing points
    swings = detect_swings(ohlcv[:-1], strength=2)
    highs = swings['highs']
    lows = swings['lows']

    if len(highs) < 2 or len(lows) < 2:
        return {}

    # Last trend-following extremes
    last_hh = highs[-1]['price']
    last_ll = lows[-1]['price']

    # Last counter-trend pivots
    # In an uptrend, we look for Higher Low (HL)
    # In a downtrend, we look for Lower High (LH)
    # For simplification, we check the most recent confirmed high/low.
    last_confirmed_high = highs[-1]
    last_confirmed_low = lows[-1]

    curr = ohlcv[-1]
    atr = compute_atr([c['h'] for c in ohlcv], [c['l'] for c in ohlcv], [c['c'] for c in ohlcv])

    structure_signal = None

    # --- BREAK DETECTION ---
    is_breaking_hh = (curr['c'] > last_hh) if CONFIRM_BREAK_ON_CLOSE else (curr['h'] > last_hh)
    is_breaking_lh = (curr['c'] > last_confirmed_high['price']) if CONFIRM_BREAK_ON_CLOSE else (curr['h'] > last_confirmed_high['price'])
    is_breaking_ll = (curr['c'] < last_ll) if CONFIRM_BREAK_ON_CLOSE else (curr['l'] < last_ll)
    is_breaking_hl = (curr['c'] < last_confirmed_low['price']) if CONFIRM_BREAK_ON_CLOSE else (curr['l'] < last_confirmed_low['price'])

    if is_breaking_hh:
        structure_signal = 'bullish_bos'
    elif is_breaking_lh:
        # Potential Bullish MSS/CHOCH (breaking a LH)
        candle_range = curr['h'] - curr['l']
        if candle_range > IMPULSE_THRESHOLD * atr:
            structure_signal = 'bullish_mss'
        else:
            structure_signal = 'bullish_choch'
    elif is_breaking_ll:
        structure_signal = 'bearish_bos'
    elif is_breaking_hl:
        # Potential Bearish MSS/CHOCH (breaking a HL)
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
