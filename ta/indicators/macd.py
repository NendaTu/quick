"""
Moving Average Convergence Divergence (MACD) Indicator
"""
from typing import List, Tuple

# --- Configuration ---
ENABLED = True
FAST = 12
SLOW = 26
SIGNAL = 9

def compute_macd(prices: List[float], fast: int = None, slow: int = None, signal: int = None) -> Tuple[float, float, float]:
    """Optimized MACD calculation."""
    if fast is None: fast = FAST
    if slow is None: slow = SLOW
    if signal is None: signal = SIGNAL

    if not ENABLED or len(prices) < slow:
        return 0.0, 0.0, 0.0

    k_fast = 2.0 / (fast + 1)
    k_slow = 2.0 / (slow + 1)
    k_signal = 2.0 / (signal + 1)

    ema_fast = sum(prices[:fast]) / fast
    ema_slow = sum(prices[:slow]) / slow
    start_idx = slow

    macd_series = []
    macd_series.append(ema_fast - ema_slow)

    for p in prices[start_idx:]:
        ema_fast = (p - ema_fast) * k_fast + ema_fast
        ema_slow = (p - ema_slow) * k_slow + ema_slow
        macd_series.append(ema_fast - ema_slow)

    if len(macd_series) < signal:
        ema_signal = sum(macd_series) / len(macd_series)
    else:
        ema_signal = sum(macd_series[:signal]) / signal
        for m in macd_series[signal:]:
            ema_signal = (m - ema_signal) * k_signal + ema_signal

    return macd_series[-1], ema_signal, macd_series[-1] - ema_signal
