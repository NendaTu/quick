"""
Support and Resistance (S/R) Detection

Identifies horizontal price levels where buying or selling interest is concentrated.

Identification:
- Swing Highs/Lows: Foundation of S/R levels.
- Multiple Touches: Confirmed levels tested at least twice.
- Flipped Levels: Broken resistance becomes support (and vice versa).
"""

from typing import List, Dict, Optional
from ta.patterns.swings import detect_swings

# --- Internal Configuration ---
ENABLED = True
TOLERANCE_PCT = 0.002 # 0.2% price tolerance for "touches"

def identify_sr(ohlcv: List[dict]) -> Dict:
    """
    Finds key horizontal support and resistance levels.
    """
    if not ENABLED or len(ohlcv) < 50:
        return {}

    swings = detect_swings(ohlcv, strength=3)
    highs = swings['highs']
    lows = swings['lows']

    current_price = ohlcv[-1]['c']

    def find_levels(points):
        levels = []
        for p in points:
            # Check for clusters (Simplified: just find unique price points)
            is_new = True
            for lv in levels:
                if abs(p['price'] / lv['price'] - 1) < TOLERANCE_PCT:
                    lv['touches'] += 1
                    is_new = False
                    break
            if is_new:
                levels.append({'price': p['price'], 'touches': 1})
        return sorted(levels, key=lambda x: x['touches'], reverse=True)

    resistance_levels = find_levels(highs)
    support_levels = find_levels(lows)

    # Filter for nearest active levels
    nearest_res = next((l for l in resistance_levels if l['price'] > current_price), None)
    nearest_sup = next((l for l in support_levels if l['price'] < current_price), None)

    return {
        'sr_resistance': nearest_res['price'] if nearest_res else None,
        'sr_support': nearest_sup['price'] if nearest_sup else None,
        'res_touches': nearest_res['touches'] if nearest_res else 0,
        'sup_touches': nearest_sup['touches'] if nearest_sup else 0
    }
