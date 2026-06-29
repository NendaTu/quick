"""
Relative Strength Index (RSI) Indicator

Standard oscillator used to measure the speed and change of price movements.
"""
from typing import List

# --- Configuration ---
# Toggle to enable/disable RSI calculation.
ENABLED = True

# Standard period for RSI calculation (default: 14).
# Higher values result in a smoother but more lagging indicator.
PERIOD = 14

# --- Strategy Thresholds ---
# RSI level below which we consider the asset oversold for scoring (+1 point).
LONG_THRESHOLD = 40.0

# RSI level above which we consider the asset overbought for scoring (-1 point).
SHORT_THRESHOLD = 60.0

# Aggressive entry floor used in Adaptive RSI mode.
# If DRT momentum is weak, we require RSI to be even lower to buy.
TIGHT_LONG = 25.0

# Aggressive entry ceiling used in Adaptive RSI mode.
# If DRT momentum is weak, we require RSI to be even higher to short.
TIGHT_SHORT = 75.0

# --- Momentum Rider Gates ---
# RSI level below which we trigger Momentum Rider (Long).
# Instead of blocking, we tighten stops and ride the parabolic move.
BUY_FLOOR = 15.0

# RSI level above which we trigger Momentum Rider (Short).
# Instead of blocking, we tighten stops and ride the parabolic move.
SHORT_CEILING = 80.0

def compute_rsi(prices: List[float], period: int = None) -> float:
    """
    Calculates the Relative Strength Index.
    Uses Wilder's Smoothing for more reliable signals in high-frequency trading.
    """
    if period is None:
        period = PERIOD

    if not ENABLED or len(prices) < period + 1:
        return 50.0

    # 1. Initial Seed (SMA)
    gains = []
    losses = []
    for i in range(1, period + 1):
        diff = prices[i] - prices[i-1]
        gains.append(max(0, diff))
        losses.append(max(0, -diff))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    # 2. Recursive Smoothing (Wilder's)
    for i in range(period + 1, len(prices)):
        diff = prices[i] - prices[i-1]
        gain = max(0, diff)
        loss = max(0, -diff)

        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))
