"""
Momentum and Volume Influx Patterns

1. CISD (Change in State of Delivery): A shift in momentum marked by breaking
   linear regression slopes or trendlines.
2. Volume Influx: Sudden surge in volume relative to recent SMA.

Identification:
- Volume Influx: CurrentVol > 1.5 * SMA(20).
- Volume Spike: CurrentVol > 2.5 * SMA(20).
- CISD: Slope change > 30% from 20-period average.
"""

import math
from typing import List, Dict, Optional
from ta.utils import calculate_sma

# --- Internal Configuration ---
ENABLED = True
INFLUX_THRESHOLD = 1.5
SPIKE_THRESHOLD = 2.5
SLOPE_CHANGE_THRESHOLD = 0.3 # 30% slope change for CISD

def identify_momentum(ohlcv: List[dict]) -> Dict:
    """
    Analyzes volume and price delivery momentum.
    """
    if not ENABLED or len(ohlcv) < 21:
        return {}

    volumes = [c['v'] for c in ohlcv]
    current_vol = volumes[-1]
    avg_vol = calculate_sma(volumes[:-1], 20)

    influx = current_vol > (INFLUX_THRESHOLD * avg_vol)
    spike = current_vol > (SPIKE_THRESHOLD * avg_vol)

    # Simple CISD (Angle/Slope Change)
    # Using last 3 and previous 20 for comparison
    def get_slope(prices):
        n = len(prices)
        if n < 2: return 0
        return (prices[-1] - prices[0]) / n

    closes = [c['c'] for c in ohlcv]
    current_slope = get_slope(closes[-5:])
    baseline_slope = get_slope(closes[-25:-5])

    cisd = False
    if baseline_slope != 0:
        slope_change = abs(current_slope - baseline_slope) / abs(baseline_slope)
        if slope_change > SLOPE_CHANGE_THRESHOLD:
            cisd = True

    return {
        'volume_influx': influx,
        'volume_spike': spike,
        'cisd_detected': cisd,
        'rel_vol': current_vol / avg_vol if avg_vol > 0 else 1.0
    }
