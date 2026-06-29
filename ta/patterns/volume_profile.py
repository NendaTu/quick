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
