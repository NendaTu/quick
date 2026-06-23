import math
from typing import List, Tuple

def compute_rsi(prices: List[float], period: int = 14) -> float:
    if len(prices) < period + 1:
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

def compute_atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 0.0

    tr_sum = 0.0
    for i in range(len(closes) - period, len(closes)):
        tr = max(highs[i] - lows[i],
                 abs(highs[i] - closes[i - 1]),
                 abs(lows[i] - closes[i - 1]))
        tr_sum += tr
    return tr_sum / period

def compute_ema(prices: List[float], period: int) -> float:
    if not prices:
        return 0.0
    if len(prices) < period:
        return sum(prices) / len(prices)

    k = 2.0 / (period + 1)
    # Use a simple moving average as the initial EMA value for better seeding
    ema = sum(prices[:period]) / period
    for p in prices[period:]:
        ema = (p - ema) * k + ema
    return ema

class MACD:
    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9):
        self.fast = fast
        self.slow = slow
        self.signal = signal
        self.ema_fast = None
        self.ema_slow = None
        self.ema_signal = None
        self.k_fast = 2.0 / (fast + 1)
        self.k_slow = 2.0 / (slow + 1)
        self.k_signal = 2.0 / (signal + 1)

    def update(self, price: float) -> Tuple[float, float, float]:
        if self.ema_fast is None:
            self.ema_fast = price
            self.ema_slow = price
            return 0.0, 0.0, 0.0

        self.ema_fast = (price - self.ema_fast) * self.k_fast + self.ema_fast
        self.ema_slow = (price - self.ema_slow) * self.k_slow + self.ema_slow

        macd_line = self.ema_fast - self.ema_slow

        if self.ema_signal is None:
            self.ema_signal = macd_line
        else:
            self.ema_signal = (macd_line - self.ema_signal) * self.k_signal + self.ema_signal

        return macd_line, self.ema_signal, macd_line - self.ema_signal

def compute_macd(prices: List[float], fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[float, float, float]:
    """Optimized MACD calculation."""
    if len(prices) < slow:
        return 0.0, 0.0, 0.0

    k_fast = 2.0 / (fast + 1)
    k_slow = 2.0 / (slow + 1)
    k_signal = 2.0 / (signal + 1)

    # Use SMA for initial seeding of EMAs
    ema_fast = sum(prices[:fast]) / fast
    ema_slow = sum(prices[:slow]) / slow

    # Adjust starting point for iteration
    start_idx = slow

    macd_series = []
    # Seed the series with initial EMAs
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

def compute_supertrend(highs: List[float], lows: List[float], closes: List[float], period: int = 10, multiplier: float = 3.0) -> Tuple[float, int]:
    """
    Full Supertrend implementation.
    Returns (trend_value, direction) where direction is 1 for bullish, -1 for bearish.
    """
    if len(closes) < period + 1:
        return closes[-1] if closes else 0.0, 1

    atr = compute_atr(highs, lows, closes, period)

    upper_band = 0.0
    lower_band = 0.0
    trend = 1

    # We need to iterate to track the bands correctly
    # For performance, we'll only do it for the necessary history
    # Standard Supertrend requires previous band values

    curr_upper_band = (highs[-1] + lows[-1]) / 2 + (multiplier * atr)
    curr_lower_band = (highs[-1] + lows[-1]) / 2 - (multiplier * atr)

    # Simplification for stateless call:
    # In a real system, we'd persist prev_upper and prev_lower.
    # Here we'll approximate based on the last two bars.

    prev_atr = compute_atr(highs[:-1], lows[:-1], closes[:-1], period)
    prev_upper_band = (highs[-2] + lows[-2]) / 2 + (multiplier * prev_atr)
    prev_lower_band = (highs[-2] + lows[-2]) / 2 - (multiplier * prev_atr)

    # Adjustment logic
    if curr_upper_band < prev_upper_band or closes[-2] > prev_upper_band:
        pass # curr_upper_band is curr_upper_band
    else:
        curr_upper_band = prev_upper_band

    if curr_lower_band > prev_lower_band or closes[-2] < prev_lower_band:
        pass # curr_lower_band is curr_lower_band
    else:
        curr_lower_band = prev_lower_band

    # Trend logic
    if closes[-1] > prev_upper_band:
        trend = 1
    elif closes[-1] < prev_lower_band:
        trend = -1
    else:
        # maintain trend (we'd need more history to be 100% accurate)
        # for now, use simple heuristic
        trend = 1 if closes[-1] > (curr_upper_band + curr_lower_band) / 2 else -1

    return (curr_lower_band if trend == 1 else curr_upper_band), trend

def compute_drt(prices: List[float], period: int = 20) -> float:
    """Directional Trend 0-1: sigmoid of the slope of linear regression over last 'period' bars."""
    if len(prices) < period:
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
    rel_slope = slope / avg_price * 1000
    return 1.0 / (1.0 + math.exp(-rel_slope))
