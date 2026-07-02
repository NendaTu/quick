"""
Momentum and Volume Influx Patterns

Detects surges in trading activity and shifts in price delivery.
"""

import math
from typing import List, Dict, Optional
from ta.utils import calculate_sma

# --- Configuration ---
# Toggle to enable/disable momentum analysis.
ENABLED = True

# Multiplier for volume surge (CurrentVol > INFLUX_THRESHOLD * SMA(20)).
INFLUX_THRESHOLD = 1.5

# Multiplier for extreme volume spike.
SPIKE_THRESHOLD = 2.5

# % slope change required to trigger CISD (Change in State of Delivery).
SLOPE_CHANGE_THRESHOLD = 0.3

def identify_momentum(ohlcv: List[dict]) -> Dict:
    """
    Analyzes volume and price delivery momentum.
    """
    if not ENABLED or len(ohlcv) < 26:
        return {}

    # Use closed candles for baseline and current for live check
    volumes = [c['v'] for c in ohlcv]
    current_vol = volumes[-1]
    avg_vol = calculate_sma(volumes[:-1], 20)

    influx = current_vol > (INFLUX_THRESHOLD * avg_vol)
    spike = current_vol > (SPIKE_THRESHOLD * avg_vol)

    def get_slope(prices):
        n = len(prices)
        if n < 2: return 0
        return (prices[-1] - prices[0]) / n

    # Note: Using live candle for slope/influx is intentional for HFT responsiveness
    # but we ensure the baseline (SMA) is stable by using volumes[:-1].
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

def get_signal(ohlcv, tf, params=None, **kwargs):
    """
    Backtestable interface for Momentum.
    Triggers on Volume Influx in the direction of the current candle.
    """
    mom = identify_momentum(ohlcv)
    if not mom.get('volume_influx'):
        return None

    last = ohlcv[-1]
    side = "long" if last['c'] > last['o'] else "short"
    price = last['c']
    move = abs(last['c'] - last['o']) * 2
    if move == 0: move = price * 0.005

    return {
        "side": side,
        "entry_price": price,
        "stop_price": price - move if side == "long" else price + move,
        "exit_price": price + (move * 2) if side == "long" else price - (move * 2)
    }
