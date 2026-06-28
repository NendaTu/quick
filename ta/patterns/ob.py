"""
Order Block (OB) and Breaker Market Structure (BMS) Recognition

Order Blocks represent areas of institutional limit orders.
Breakers (BMS) occur when an established OB is invalidated and flips polarity.

Identification:
- Bullish OB: Last bearish candle immediately preceding a strong bullish impulsive move.
- Bearish OB: Last bullish candle immediately preceding a strong bearish impulsive move.
- Mitigation: Price touching the OB zone.
- Breaker (BMS): Price closing beyond the OB boundary in the opposite direction.
"""

from typing import List, Dict, Optional
from ta.indicators.atr import compute_atr

# --- Internal Configuration ---
ENABLED = True
IMPULSE_MULT = 1.5 # Impulse candle range must be > 1.5x ATR
INVALIDATION_MARGIN = 0.001 # 0.1% break of OB creates a Breaker

def detect_order_blocks(ohlcv: List[dict]) -> Dict:
    """
    Identifies order blocks and breaker blocks.
    """
    if not ENABLED or len(ohlcv) < 20:
        return {}

    highs = [c['h'] for c in ohlcv]
    lows = [c['l'] for c in ohlcv]
    closes = [c['c'] for c in ohlcv]
    atr = compute_atr(highs, lows, closes)

    obs = []

    # 1. Identify OBs in history
    for i in range(1, len(ohlcv) - 1):
        prev = ohlcv[i-1]
        curr = ohlcv[i]
        nxt = ohlcv[i+1]

        # Bullish OB (Bearish candle followed by Bullish Impulse)
        if curr['c'] < curr['o']: # Bearish candle
            impulse_range = nxt['h'] - nxt['l']
            if impulse_range > IMPULSE_MULT * atr and nxt['c'] > curr['h']:
                obs.append({
                    'type': 'bullish',
                    'top': curr['h'],
                    'bottom': curr['l'],
                    'index': i,
                    'state': 'active'
                })

        # Bearish OB (Bullish candle followed by Bearish Impulse)
        elif curr['c'] > curr['o']: # Bullish candle
            impulse_range = nxt['h'] - nxt['l']
            if impulse_range > IMPULSE_MULT * atr and nxt['c'] < curr['l']:
                obs.append({
                    'type': 'bearish',
                    'top': curr['h'],
                    'bottom': curr['l'],
                    'index': i,
                    'state': 'active'
                })

    if not obs:
        return {'ob_count': 0, 'nearest_ob': None}

    # 2. Update states (Mitigation and Breaker logic)
    last_candle = ohlcv[-1]

    for ob in obs:
        # Check action after formation
        post_ob_candles = ohlcv[ob['index']+2:]

        for pc in post_ob_candles:
            # Breaker Check
            if ob['type'] == 'bullish' and pc['c'] < ob['bottom'] * (1 - INVALIDATION_MARGIN):
                ob['state'] = 'breaker'
            elif ob['type'] == 'bearish' and pc['c'] > ob['top'] * (1 + INVALIDATION_MARGIN):
                ob['state'] = 'breaker'
            # Mitigation Check
            elif pc['h'] >= ob['bottom'] and pc['l'] <= ob['top']:
                if ob['state'] == 'active':
                    ob['state'] = 'mitigated'

    # 3. Output nearest active/breaker zones
    active_obs = [ob for ob in obs if ob['state'] == 'active']
    breakers = [ob for ob in obs if ob['state'] == 'breaker']

    return {
        'ob_active_count': len(active_obs),
        'breaker_count': len(breakers),
        'nearest_ob_type': active_obs[-1]['type'] if active_obs else None,
        'has_breaker': len(breakers) > 0
    }
