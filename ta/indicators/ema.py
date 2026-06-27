"""
Exponential Moving Average (EMA) Indicator
"""
from typing import List

# --- Configuration ---
ENABLED = True

def compute_ema(prices: List[float], period: int) -> float:
    if not ENABLED or not prices:
        return 0.0
    if len(prices) < period:
        return sum(prices) / len(prices)

    k = 2.0 / (period + 1)
    # Use a simple moving average as the initial EMA value for better seeding
    ema = sum(prices[:period]) / period
    for p in prices[period:]:
        ema = (p - ema) * k + ema
    return ema
