"""
Buy-Side Liquidity (BSL) and Sell-Side Liquidity (SSL) Recognition

Identifies clusters of pending orders located above recent swing highs (BSL)
or below recent swing lows (SSL).
"""

from typing import List, Dict, Optional
from ta.patterns.swings import detect_swings
from ta.patterns.sessions import is_core_session

# --- Configuration ---
# Toggle to enable/disable liquidity detection.
ENABLED = True

# Standard lookback period for identifying liquidity pools.
LOOKBACK = 50

# Buffer (%) added to swing extremes to define the liquidity zone.
BUFFER_PCT = 0.001

def identify_liquidity(ohlcv: List[dict], lookback: int = LOOKBACK, swing_strength: int = 2, hub_filter: Optional[str] = None, start_ts: Optional[float] = None) -> Dict:
    """
    Identifies BSL and SSL levels from recent price action.

    [OVERNIGHT SUPPORT]: If hub_filter is provided, only uses candles from that hub's Core session.
    [ATR SUPPORT]: If start_ts is provided, only uses candles that occurred on or after this timestamp.
    """
    if not ENABLED or len(ohlcv) < lookback:
        return {}

    # Use closed candles for level identification to prevent repainting/noise
    closed_ohlcv = ohlcv[:-1] if len(ohlcv) > lookback else ohlcv

    if hub_filter:
        relevant = [c for c in closed_ohlcv[-300:] if is_core_session(c['ts'], hub_filter)]
    elif start_ts:
        relevant = [c for c in closed_ohlcv if c['ts'] >= start_ts]
    else:
        relevant = closed_ohlcv[-lookback:]

    if len(relevant) > lookback:
        relevant = relevant[-lookback:]

    if not relevant: return {}

    highs = [c['h'] for c in relevant]
    lows = [c['l'] for c in relevant]

    max_high = max(highs)
    min_low = min(lows)

    swings = detect_swings(relevant, strength=swing_strength)

    # 1. Immediate (last swing)
    immediate_bsl = swings['highs'][-1]['price'] if swings['highs'] else max_high
    immediate_ssl = swings['lows'][-1]['price'] if swings['lows'] else min_low

    # 2. All recent levels for scanning
    all_bsl = [s['price'] * (1 + BUFFER_PCT) for s in swings['highs']]
    all_ssl = [s['price'] * (1 - BUFFER_PCT) for s in swings['lows']]

    return {
        'bsl_level': immediate_bsl * (1 + BUFFER_PCT),
        'ssl_level': immediate_ssl * (1 - BUFFER_PCT),
        'internal_bsl': swings['highs'][-2]['price'] if len(swings['highs']) > 1 else immediate_bsl,
        'internal_ssl': swings['lows'][-2]['price'] if len(swings['lows']) > 1 else immediate_ssl,
        'all_bsl': sorted(list(set(all_bsl))),
        'all_ssl': sorted(list(set(all_ssl)), reverse=True),
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
