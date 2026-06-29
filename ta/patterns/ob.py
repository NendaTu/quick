"""
Order Block (OB) and Breaker Market Structure (BMS) Recognition

Order Blocks represent areas of institutional limit orders.
"""

from typing import List, Dict, Optional
from ta.indicators.atr import compute_atr

# --- Configuration ---
# Toggle to enable/disable Order Block detection.
ENABLED = True

# Impulse candle range must be > IMPULSE_MULT * ATR.
IMPULSE_MULT = 1.5

# Margin (%) required to invalidate an OB and turn it into a Breaker.
INVALIDATION_MARGIN = 0.001

def detect_order_blocks(ohlcv: List[dict]) -> Dict:
    """
    Identifies order blocks and breaker blocks.
    Only considers closed candles for OB formation.
    """
    if not ENABLED or len(ohlcv) < 21:
        return {}

    closed_ohlcv = ohlcv[:-1]
    highs = [c['h'] for c in closed_ohlcv]
    lows = [c['l'] for c in closed_ohlcv]
    closes = [c['c'] for c in closed_ohlcv]
    atr = compute_atr(highs, lows, closes)

    obs = []

    # 1. Identify OBs in history
    for i in range(1, len(closed_ohlcv) - 1):
        prev = closed_ohlcv[i-1]
        curr = closed_ohlcv[i]
        nxt = closed_ohlcv[i+1]

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

    # 2. Update states using live data
    last_candle = ohlcv[-1]

    for ob in obs:
        post_ob_candles = ohlcv[ob['index']+2:]
        for pc in post_ob_candles:
            if ob['type'] == 'bullish' and pc['c'] < ob['bottom'] * (1 - INVALIDATION_MARGIN):
                ob['state'] = 'breaker'
            elif ob['type'] == 'bearish' and pc['c'] > ob['top'] * (1 + INVALIDATION_MARGIN):
                ob['state'] = 'breaker'
            elif pc['h'] >= ob['bottom'] and pc['l'] <= ob['top']:
                if ob['state'] == 'active':
                    ob['state'] = 'mitigated'

    active_obs = [ob for ob in obs if ob['state'] == 'active']
    breakers = [ob for ob in obs if ob['state'] == 'breaker']

    return {
        'ob_active_count': len(active_obs),
        'breaker_count': len(breakers),
        'nearest_ob_type': active_obs[-1]['type'] if active_obs else None,
        'has_breaker': len(breakers) > 0
    }
