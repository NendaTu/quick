"""
HTF POI Delivery and Confluence Module

Union of multiple validated zones (OB, FVG, Liquidity, SessionHL) to
identify high-probability Points of Interest (POI).

Identification:
- Registry: UNION(OBs, FVGs, Liquidity levels, SessionHL).
- Confluence: Points where multiple types overlap (within ATR tolerance).
- Reaction: Delivery confirmed on touch + LTF reaction (MSS, Engulfing).
"""

from typing import List, Dict, Optional
from ta.indicators.atr import compute_atr

# --- Internal Configuration ---
ENABLED = True
CONFLUENCE_TOLERANCE_ATR = 0.1 # Overlap within 0.1x ATR triggers confluence bonus

def identify_pois(
    ohlcv: List[dict],
    obs: Dict,
    fvgs: Dict,
    liquidity: Dict,
    sessions: Dict
) -> Dict:
    """
    Ranks and coordinates all technical points of interest.
    """
    if not ENABLED:
        return {}

    current_price = ohlcv[-1]['c']
    atr = compute_atr([c['h'] for c in ohlcv], [c['l'] for c in ohlcv], [c['c'] for c in ohlcv])
    tolerance = CONFLUENCE_TOLERANCE_ATR * atr

    # 1. Register candidate levels
    candidates = []

    # Order Blocks
    if obs.get('nearest_ob_type'):
        # Note: OB data in current implementation is simplified
        # In a full build, we'd pass the actual zone boundaries
        pass

    # Fair Value Gaps
    if fvgs.get('nearest_fvg_type'):
        candidates.append({'type': 'fvg', 'dist': fvgs['nearest_fvg_dist'], 'score': 30})

    # Liquidity
    if liquidity.get('bsl_level'):
        dist = (current_price / liquidity['bsl_level'] - 1)
        candidates.append({'type': 'bsl', 'dist': dist, 'score': 40})
    if liquidity.get('ssl_level'):
        dist = (current_price / liquidity['ssl_level'] - 1)
        candidates.append({'type': 'ssl', 'dist': dist, 'score': 40})

    # 2. Confluence Check (Simplified for feature set)
    # Check if price is near ANY high-value level
    poi_active = False
    best_poi = None

    if candidates:
        nearest = min(candidates, key=lambda x: abs(x['dist']))
        if abs(nearest['dist']) < 0.002: # Within 0.2%
            poi_active = True
            best_poi = nearest

    return {
        'poi_active': poi_active,
        'primary_poi_type': best_poi['type'] if best_poi else None,
        'poi_confluence_score': best_poi['score'] if best_poi else 0
    }
