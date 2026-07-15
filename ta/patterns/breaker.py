"""
Breaker Block (Breaker) Identification Module

How it works:
1. This module identifies "Breaker Blocks"—which are failed Order Blocks
   that have flipped polarity.
2. A Bullish Breaker is a failed bearish Order Block. When price closes
   above the top of a Bearish OB, that block flips polarity to become
   a source of future demand (Bullish Breaker).
3. A Bearish Breaker is a failed bullish Order Block. When price closes
   below the bottom of a Bullish OB, that block flips polarity to become
   a source of future supply (Bearish Breaker).
4. Retests / Mitigation: Once a breaker forms, it can be mitigated/filled
   if subsequent candles wick into its range.
"""

from typing import List, Dict, Optional
from ta.patterns.ob import compute_atr_series

# --- Configuration ---
# Toggle to enable/disable Breaker Block detection.
ENABLED = True

# Standard impulse candle multiplier (matching ob.py).
IMPULSE_MULT = 1.5

# Margin (%) required to invalidate an OB and turn it into a Breaker.
INVALIDATION_MARGIN = 0.001

def detect_breakers(
    ohlcv: List[dict],
    period: int = 14,
    invalidation_margin: float = INVALIDATION_MARGIN,
    impulse_mult: float = IMPULSE_MULT
) -> Dict:
    """
    Identifies active (unmitigated) and historical breaker blocks.
    Evaluates signals strictly using closed candles to prevent look-ahead bias and repainting.
    Judges historic candles against contemporary ATR series.
    """
    if not ENABLED or len(ohlcv) < period + 3:
        return {
            'breaker_count': 0,
            'nearest_breaker_type': None,
            'breakers': [],
            'all_breakers': []
        }

    # Evaluate using closed candles only to prevent repainting
    closed_ohlcv = ohlcv[:-1]
    highs = [c['h'] for c in closed_ohlcv]
    lows = [c['l'] for c in closed_ohlcv]
    closes = [c['c'] for c in closed_ohlcv]

    # Compute rolling ATR series to prevent historical drift/repainting [REPAIR-001]
    atr_series = compute_atr_series(highs, lows, closes, period)

    obs = []

    # 1. Identify Candidate OBs in history
    for i in range(1, len(closed_ohlcv) - 1):
        curr = closed_ohlcv[i]
        nxt = closed_ohlcv[i+1]
        atr_val = atr_series[i]

        if atr_val <= 0.0:
            continue

        impulse_range = nxt['h'] - nxt['l']
        is_impulsive = impulse_range > (impulse_mult * atr_val)

        # Doji Hardening: treat open == close as bearish/bullish based on next direction
        is_bearish = curr['c'] < curr['o'] or (curr['c'] == curr['o'] and nxt['c'] > curr['h'])
        is_bullish = curr['c'] > curr['o'] or (curr['c'] == curr['o'] and nxt['c'] < curr['l'])

        if is_bearish and is_impulsive and nxt['c'] > curr['h']:
            obs.append({
                'type': 'bullish',  # Originally a Bullish OB
                'top': curr['h'],
                'bottom': curr['l'],
                'index': i,
                'ts': curr['ts']
            })
        elif is_bullish and is_impulsive and nxt['c'] < curr['l']:
            obs.append({
                'type': 'bearish',  # Originally a Bearish OB
                'top': curr['h'],
                'bottom': curr['l'],
                'index': i,
                'ts': curr['ts']
            })

    breakers = []

    # 2. Check for invalidations (breaks) to identify Breaker Blocks
    for ob in obs:
        post_ob_candles = closed_ohlcv[ob['index']+2:]
        for idx, pc in enumerate(post_ob_candles):
            is_broken = False
            breaker_type = None

            if ob['type'] == 'bullish' and pc['c'] < ob['bottom'] * (1 - invalidation_margin):
                # Bullish OB fails and becomes a Bearish Breaker
                is_broken = True
                breaker_type = 'bearish'
            elif ob['type'] == 'bearish' and pc['c'] > ob['top'] * (1 + invalidation_margin):
                # Bearish OB fails and becomes a Bullish Breaker
                is_broken = True
                breaker_type = 'bullish'

            if is_broken:
                # The index/timestamp where the break occurred
                breaker_formation_idx = ob['index'] + 2 + idx
                breakers.append({
                    'type': breaker_type,
                    'top': ob['top'],
                    'bottom': ob['bottom'],
                    'index': breaker_formation_idx,
                    'ts': pc['ts'],
                    'state': 'active'
                })
                break  # This block is now permanently a Breaker, stop scanning for break

    # 3. Check for mitigation of Breaker Blocks by subsequent candles up to the current live candle
    for br in breakers:
        post_breaker_candles = ohlcv[br['index']+1:]
        for pc in post_breaker_candles:
            if pc['l'] <= br['top'] and pc['h'] >= br['bottom']:
                br['state'] = 'mitigated'
                break

    active_breakers = [br for br in breakers if br['state'] == 'active']

    return {
        'breaker_count': len(active_breakers),
        'nearest_breaker_type': active_breakers[-1]['type'] if active_breakers else None,
        'breakers': active_breakers,
        'all_breakers': breakers
    }
