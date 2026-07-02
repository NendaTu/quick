"""
Order Book Imbalance Delta (OBID)

Tracks the rate of change in order book pressure.
"""
from typing import List

# --- Configuration ---
ENABLED = True

# Weight for the imbalance delta in the scoring model.
SCORE_WEIGHT = 0.5

# Lookback period (ticks) to calculate the delta.
DELTA_LOOKBACK = 5

def compute_imbalance_delta(current_imb: float, history: List[float], lookback: int = None) -> float:
    """
    Calculates the change in imbalance over a specific lookback.
    """
    if not ENABLED or not history:
        return 0.0

    if lookback is None:
        lookback = DELTA_LOOKBACK

    prev_imb = history[-min(len(history), lookback)]
    return current_imb - prev_imb

def get_signal(ohlcv, tf, params=None, **kwargs):
    """
    Backtestable interface for Book Delta.
    Note: Standard OHLCV does not contain order book metrics.
    """
    return None
