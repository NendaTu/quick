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

    # Use closed candles for level identification to prevent repainting/noise
    closed_ohlcv = ohlcv[:-1] if len(ohlcv) > lookback else ohlcv
    relevant = closed_ohlcv[-lookback:]

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
        'internal_bsl': swings['highs'][-2]['price'] if len(swings['highs']) > 1 else immediate_bsl,
        'internal_ssl': swings['lows'][-2]['price'] if len(swings['lows']) > 1 else immediate_ssl,
        'range_high': max_high,
        'range_low': min_low
    }

def get_signal(ohlcv, tf, params=None, **kwargs):
    """
    Backtestable interface for Liquidity.
    Triggers LONG on SSL touch (reversal), SHORT on BSL touch.
    """
    liq = identify_liquidity(ohlcv)
    if not liq: return None

    price = ohlcv[-1]['c']
    # If price swept SSL and is now above it (mean reversion)
    if ohlcv[-1]['l'] <= liq['ssl_level'] and price > liq['ssl_level']:
        return {
            "side": "long",
            "entry_price": price,
            "stop_price": ohlcv[-1]['l'] * 0.999,
            "exit_price": liq['bsl_level']
        }
    # If price swept BSL and is now below it
    if ohlcv[-1]['h'] >= liq['bsl_level'] and price < liq['bsl_level']:
        return {
            "side": "short",
            "entry_price": price,
            "stop_price": ohlcv[-1]['h'] * 1.001,
            "exit_price": liq['ssl_level']
        }
    return None
