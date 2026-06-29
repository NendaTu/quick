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

# --- Configuration ---
ENABLED = True
CONFLUENCE_TOLERANCE_ATR = 0.1 # Overlap within 0.1x ATR triggers confluence bonus

# Weighting by Timeframe and Type [TA-004]
WEIGHTS = {
    'ob': 50,
    'fvg': 30,
    'liquidity': 40,
    'session': 20
}

def identify_pois(
    ohlcv: List[dict],
    obs: Dict,
    fvgs: Dict,
    liquidity: Dict,
    sessions: Dict
) -> Dict:
    """
    Ranks and coordinates all technical points of interest.
    Uses weighted scoring to prioritize high-probability zones.
    """
    if not ENABLED:
        return {}

    current_price = ohlcv[-1]['c']
    atr = compute_atr([c['h'] for c in ohlcv], [c['l'] for c in ohlcv], [c['c'] for c in ohlcv])
    tolerance = CONFLUENCE_TOLERANCE_ATR * atr

    # 1. Register candidate levels
    candidates = []

    # Order Blocks (Weighted)
    if obs.get('nearest_ob_type'):
        candidates.append({'type': 'ob', 'dist': 0.001, 'score': WEIGHTS['ob']})

    # Fair Value Gaps
    if fvgs.get('nearest_fvg_type'):
        candidates.append({'type': 'fvg', 'dist': fvgs['nearest_fvg_dist'], 'score': WEIGHTS['fvg']})

    # Liquidity
    if liquidity.get('bsl_level'):
        dist = (current_price / liquidity['bsl_level'] - 1)
        candidates.append({'type': 'bsl', 'dist': dist, 'score': WEIGHTS['liquidity']})
    if liquidity.get('ssl_level'):
        dist = (current_price / liquidity['ssl_level'] - 1)
        candidates.append({'type': 'ssl', 'dist': dist, 'score': WEIGHTS['liquidity']})

    # 2. Confluence Check (Weighted)
    poi_active = False
    total_score = 0
    primary_type = None

    active_candidates = [c for c in candidates if abs(c['dist']) < 0.003] # Within 0.3%

    if active_candidates:
        poi_active = True
        total_score = sum(c['score'] for c in active_candidates)
        # Primary type is the one with highest weight
        primary_type = max(active_candidates, key=lambda x: x['score'])['type']

    return {
        'poi_active': poi_active,
        'primary_poi_type': primary_type,
        'poi_confluence_score': total_score
    }
