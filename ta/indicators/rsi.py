"""
Relative Strength Index (RSI) Indicator
"""
from typing import List

# --- Configuration ---
ENABLED = True

def compute_rsi(prices: List[float], period: int = 14) -> float:
    if not ENABLED or len(prices) < period + 1:
        return 50.0

    gains = 0.0
    losses = 0.0

    for i in range(1, period + 1):
        diff = prices[-i] - prices[-i-1]
        if diff > 0:
            gains += diff
        else:
            losses -= diff

    avg_gain = gains / period
    avg_loss = losses / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))
