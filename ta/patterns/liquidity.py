"""
Buy-Side Liquidity (BSL) and Sell-Side Liquidity (SSL) Recognition

Identifies clusters of pending orders located above recent swing highs (BSL)
or below recent swing lows (SSL).

Identification:
- BSL Level: Max(High) over a lookback period + a buffer.
- SSL Level: Min(Low) over a lookback period - a buffer.

Multi-tier tracking:
- Immediate (20-50 bars lookback)
- Session extremes (Daily/Weekly)
"""

from typing import List, Dict, Optional
from ta.patterns.swings import detect_swings

# --- Internal Configuration ---
ENABLED = True
DEFAULT_LOOKBACK = 50
BUFFER_PCT = 0.001 # 0.1% buffer for liquidity clusters

def identify_liquidity(ohlcv: List[dict], lookback: int = 50) -> Dict:
    """
    Identifies BSL and SSL levels from recent price action.
    """
    if not ENABLED or len(ohlcv) < lookback:
        return {}

    relevant = ohlcv[-lookback:]
    highs = [c['h'] for c in relevant]
    lows = [c['l'] for c in relevant]

    max_high = max(highs)
    min_low = min(lows)

    # Use swings for more precise structural liquidity
    swings = detect_swings(relevant, strength=2)

    immediate_bsl = swings['highs'][-1]['price'] if swings['highs'] else max_high
    immediate_ssl = swings['lows'][-1]['price'] if swings['lows'] else min_low

    return {
        'bsl_level': immediate_bsl * (1 + BUFFER_PCT),
        'ssl_level': immediate_ssl * (1 - BUFFER_PCT),
        'range_high': max_high,
        'range_low': min_low
    }
