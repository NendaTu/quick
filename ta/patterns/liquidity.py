"""
Buy-Side Liquidity (BSL) and Sell-Side Liquidity (SSL) Recognition

Identifies clusters of pending orders located above recent swing highs (BSL)
or below recent swing lows (SSL).
"""

from typing import List, Dict, Optional
from ta.patterns.swings import detect_swings

# --- Configuration ---
# Toggle to enable/disable liquidity detection.
ENABLED = True

# Standard lookback period for identifying liquidity pools.
LOOKBACK = 50

# Buffer (%) added to swing extremes to define the liquidity zone.
BUFFER_PCT = 0.001

def identify_liquidity(ohlcv: List[dict], lookback: int = None) -> Dict:
    """
    Identifies BSL and SSL levels from recent price action.
    """
    if lookback is None:
        lookback = LOOKBACK

    if not ENABLED or len(ohlcv) < lookback:
        return {}

    relevant = ohlcv[-lookback:]
    highs = [c['h'] for c in relevant]
    lows = [c['l'] for c in relevant]

    max_high = max(highs)
    min_low = min(lows)

    swings = detect_swings(relevant, strength=2)

    immediate_bsl = swings['highs'][-1]['price'] if swings['highs'] else max_high
    immediate_ssl = swings['lows'][-1]['price'] if swings['lows'] else min_low

    return {
        'bsl_level': immediate_bsl * (1 + BUFFER_PCT),
        'ssl_level': immediate_ssl * (1 - BUFFER_PCT),
        'range_high': max_high,
        'range_low': min_low
    }
