"""
Fair Value Gap (FVG) Recognition Module

A Fair Value Gap occurs in a three-candle sequence when there is a lack of price overlap between
the wick of the first candle and the wick of the third candle.
"""

from typing import List, Dict, Optional

# --- Configuration ---
# Toggle to enable/disable FVG detection.
ENABLED = True

# Number of candles to scan for active (unfilled) gaps.
HISTORY_DEPTH = 50

# Timeframe used for FVG detection (e.g., '5m' for HTF confluence).
TIMEFRAME = "5m"

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
