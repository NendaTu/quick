"""
Intraday Volume Profiling

Identifies High Volume Nodes (HVN) and the Point of Control (POC).
"""
from typing import List, Dict

# --- Configuration ---
ENABLED = True

# Number of candles to use for the session volume profile.
LOOKBACK = 100

def identify_poc(ohlcv: List[dict], lookback: int = None) -> float:
    """
    Identifies the price level with the highest transacted volume.
    """
    if not ENABLED or not ohlcv:
        return 0.0

    if lookback is None:
        lookback = LOOKBACK

    relevant = ohlcv[-min(len(ohlcv), lookback):]

    # Bucket prices (using 0.1% bins)
    profile = {}
    for c in relevant:
        # Use mid-price for the candle's volume bucket
        price = (c['h'] + c['l']) / 2
        bin = round(price, 4) # Adjust precision based on asset
        profile[bin] = profile.get(bin, 0) + c['v']

    if not profile:
        return ohlcv[-1]['c']

    poc = max(profile, key=profile.get)
    return poc

def get_signal(ohlcv, tf, params=None, **kwargs):
    """
    Backtestable interface for Volume Profile.
    Triggers LONG on POC touch from below (support), SHORT on touch from above.
    """
    poc = identify_poc(ohlcv)
    if not poc: return None

    price = ohlcv[-1]['c']
    prev_price = ohlcv[-2]['c'] if len(ohlcv) > 1 else price

    # Simple mean reversion towards POC
    if prev_price < poc and ohlcv[-1]['h'] >= poc:
        return {
            "side": "long",
            "entry_price": price,
            "stop_price": ohlcv[-1]['l'] * 0.999,
            "exit_price": price * 1.01
        }
    if prev_price > poc and ohlcv[-1]['l'] <= poc:
        return {
            "side": "short",
            "entry_price": price,
            "stop_price": ohlcv[-1]['h'] * 1.001,
            "exit_price": price * 0.99
        }
    return None
