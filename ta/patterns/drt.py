"""
Directional Trend (DRT) Pattern Recognition

Calculates the slope of linear regression over a lookback period and squashes
it via Sigmoid into a 0.0-1.0 pulse where 0.5 is neutral.
"""

import math
from typing import List

# --- Configuration ---
# Toggle to enable/disable DRT calculation.
ENABLED = True

# Number of points used for the linear regression calculation.
PERIOD = 20

# Minimum trend offset from 0.5 required to consider the market "trending".
# Example: 0.1 means DRT must be < 0.4 or > 0.6.
STRENGTH_MIN = 0.1

def compute_drt(prices: List[float], period: int = None) -> float:
    """Directional Trend 0-1: sigmoid of the slope of linear regression."""
    if period is None:
        period = PERIOD

    if not ENABLED or len(prices) < period:
        return 0.5

    x = list(range(period))
    y = prices[-period:]
    n = period
    sum_x = sum(x)
    sum_y = sum(y)
    sum_xy = sum(xi * yi for xi, yi in zip(x, y))
    sum_x2 = sum(xi**2 for xi in x)
    denominator = (n * sum_x2 - sum_x**2)
    slope = (n * sum_xy - sum_x * sum_y) / denominator if denominator != 0 else 0

    avg_price = sum_y / n
    if avg_price == 0:
        return 0.5
    # Scaled for sensitivity: relative slope * 1000
    rel_slope = slope / avg_price * 1000
    return 1.0 / (1.0 + math.exp(-rel_slope))
