"""
Swing High/Low Detection Module

Identifies local peaks and troughs in price action, which serve as the foundation
for Market Structure (BOS, MSS), Support/Resistance, and Liquidity patterns.

A Swing Low is a trough where Low[t] < Low[t-1] and Low[t] < Low[t+1].
A Swing High is a peak where High[t] > High[t-1] and High[t] > High[t+1].
"""

from typing import List, Dict, Optional

_swing_cache = {}

# --- Internal Configuration ---
ENABLED = True
STRENGTH = 2 # Number of bars required on each side to confirm a swing point

def detect_swings(ohlcv: List[dict], strength: int = 2) -> Dict[str, List[dict]]:
    """
    Scans OHLCV data for confirms swing high and low points.
    [PERF] Implements bar-count caching to avoid O(N^2) scans.
    """
    if not ENABLED or len(ohlcv) < (strength * 2 + 1):
        return {'highs': [], 'lows': []}

    # 1. Check Cache
    # We use (first_ts, last_ts, first_close, last_close, len, strength) as a fingerprint to prevent cross-symbol contamination
    cache_key = (ohlcv[0]['ts'], ohlcv[-1]['ts'], ohlcv[0]['c'], ohlcv[-1]['c'], len(ohlcv), strength)
    if cache_key in _swing_cache:
        return _swing_cache[cache_key]

    swing_highs = []
    swing_lows = []

    for i in range(strength, len(ohlcv) - strength):
        curr = ohlcv[i]
        is_high = True
        is_low = True

        for j in range(1, strength + 1):
            # Check for higher high
            if ohlcv[i-j]['h'] >= curr['h'] or ohlcv[i+j]['h'] > curr['h']:
                is_high = False
            # Check for lower low
            if ohlcv[i-j]['l'] <= curr['l'] or ohlcv[i+j]['l'] < curr['l']:
                is_low = False

        if is_high:
            swing_highs.append({'price': curr['h'], 'index': i, 'timestamp': curr['ts']})
        if is_low:
            swing_lows.append({'price': curr['l'], 'index': i, 'timestamp': curr['ts']})

    res = {
        'highs': swing_highs,
        'lows': swing_lows
    }

    if len(_swing_cache) > 1000: _swing_cache.clear()
    _swing_cache[cache_key] = res
    return res

def get_signal(ohlcv, tf, params=None, **kwargs):
    """
    Backtestable interface for Swings.
    Triggers LONG on Swing Low, SHORT on Swing High.
    """
    swings = detect_swings(ohlcv, strength=STRENGTH)
    if not swings['highs'] and not swings['lows']:
        return None

    last_idx = len(ohlcv) - 1
    # Check if a swing was confirmed at current index - STRENGTH
    is_sh = any(s['index'] == (last_idx - STRENGTH) for s in swings['highs'])
    is_sl = any(s['index'] == (last_idx - STRENGTH) for s in swings['lows'])

    if not is_sh and not is_sl:
        return None

    price = ohlcv[-1]['c']
    # Use a dummy move for SL/TP
    move = (ohlcv[-1]['h'] - ohlcv[-1]['l']) * 2
    if move == 0: move = price * 0.005

    if is_sl:
        return {
            "side": "long",
            "entry_price": price,
            "stop_price": price - move,
            "exit_price": price + (move * 2)
        }
    if is_sh:
        return {
            "side": "short",
            "entry_price": price,
            "stop_price": price + move,
            "exit_price": price - (move * 2)
        }
    return None
