"""
1. Summary: Order book quantity volume imbalance delta calculator.
2. Description: Calculates volume imbalances between the top bids and asks inside the active order book.
3. Context: Used by scoring and feature extraction components to gauge short-term micro liquidity pressure.
"""
from typing import List

# --- Configuration ---
ENABLED = True

# Weight for the imbalance delta in the scoring model.
# [OP Roadmap] Increased for higher frequency responsiveness.
SCORE_WEIGHT = 1.5

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
