"""
Fair Value Gap (FVG) Recognition Module

A Fair Value Gap occurs in a three-candle sequence when there is a lack of price overlap between
the wick of the first candle and the wick of the third candle. This indicates a zone of
inefficiency or liquidity imbalance.

States of an FVG:
1. UNFILLED: The gap has been created but price has not yet returned to it.
2. MITIGATED: Price has touched or entered the gap but the candle closed outside of it.
3. ENGAGED: A candle has closed inside the gap range.
4. INVERTED (IFVG): Price has fully passed through the gap and treated it as support/resistance
   from the opposite side.

Config Settings:
- ENABLED: Boolean toggle to activate detection.
- HISTORY_DEPTH: How many candles to scan for unfilled gaps.
"""

from typing import List, Dict, Optional

# --- Internal Configuration ---
ENABLED = True
HISTORY_DEPTH = 50 # Default if not provided by global config

def detect_fvgs(ohlcv: List[dict], depth: int = 50) -> Dict:
    """
    Analyzes the provided OHLCV data for Fair Value Gaps.

    Args:
        ohlcv: List of candle dictionaries containing 'h', 'l', 'c'.
        depth: How many candles back to scan for gaps.

    Returns:
        A dictionary containing the nearest FVG details and global gap stats.
    """
    if not ENABLED or len(ohlcv) < 3:
        return {}

    # Slice to relevant history
    scan_start = max(0, len(ohlcv) - depth)
    relevant_candles = ohlcv[scan_start:]

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

    # 2. Update states based on subsequent price action
    current_price = ohlcv[-1]['c']

    for fvg in fvgs:
        # Check action from the candle AFTER the gap (index + 2) to current
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
                    break # Stop tracking once inverted
                elif closes_inside:
                    fvg['state'] = 'engaged'
                elif touches and fvg['state'] == 'unfilled':
                    fvg['state'] = 'mitigated'
            else: # bearish
                # If price rises fully above the gap, it becomes Inverted
                if close > fvg['top']:
                    fvg['state'] = 'inverted'
                    break # Stop tracking once inverted
                elif closes_inside:
                    fvg['state'] = 'engaged'
                elif touches and fvg['state'] == 'unfilled':
                    fvg['state'] = 'mitigated'

    # 3. Find the nearest active (not yet fully filled/inverted) FVG
    active_fvgs = [f for f in fvgs if f['state'] != 'inverted']

    # Optimization: Filter out historic gaps that are now terminal/inverted to avoid post-processing
    # Note: In this stateless detector, we can only filter within the current depth

    nearest = None
    if active_fvgs:
        # Sort by proximity to current price
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
