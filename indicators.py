import math
from collections import deque
from typing import List, Tuple

def compute_rsi(prices: List[float], period: int = 14) -> float:
    if len(prices) < period + 1:
        return 50.0
    deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    gains = [d if d > 0 else 0 for d in deltas[-period:]]
    losses = [-d if d < 0 else 0 for d in deltas[-period:]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))

def compute_atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(closes)):
        tr = max(highs[i] - lows[i],
                 abs(highs[i] - closes[i - 1]),
                 abs(lows[i] - closes[i - 1]))
        trs.append(tr)
    return sum(trs[-period:]) / period

def compute_ema(prices: List[float], period: int) -> float:
    if len(prices) < period:
        return prices[-1] if prices else 0.0
    k = 2.0 / (period + 1)
    ema = prices[0]
    for p in prices[1:]:
        ema = (p - ema) * k + ema
    return ema

def compute_macd(prices: List[float], fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[float, float, float]:
    if len(prices) < slow:
        return 0.0, 0.0, 0.0
    ema_fast = compute_ema(prices, fast)
    ema_slow = compute_ema(prices, slow)
    macd_line = ema_fast - ema_slow
    # signal line: we need a series of macd values; approximate using last N
    if len(prices) < slow + signal:
        return macd_line, macd_line, 0.0
    macd_series = []
    for i in range(slow, len(prices)):
        ema_fast_i = compute_ema(prices[:i + 1], fast)
        ema_slow_i = compute_ema(prices[:i + 1], slow)
        macd_series.append(ema_fast_i - ema_slow_i)
    signal_line = compute_ema(macd_series, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram

def compute_supertrend(highs: List[float], lows: List[float], closes: List[float], period: int = 10, multiplier: float = 3.0) -> float:
    if len(closes) < period:
        return closes[-1] if closes else 0.0
    atr = compute_atr(highs, lows, closes, period)
    mid = [(h + l) / 2 for h, l in zip(highs, lows)]
    upper_bands = [m + multiplier * atr for m in mid]
    lower_bands = [m - multiplier * atr for m in mid]
    # simplistic: just return current lower band as "super trend" value
    return lower_bands[-1] if lower_bands else closes[-1]

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
    slope = (n * sum_xy - sum_x * sum_y) / (n * sum_x2 - sum_x**2) if (n * sum_x2 - sum_x**2) != 0 else 0
    # scale slope by price to get relative trend
    avg_price = sum_y / n
    if avg_price == 0:
        return 0.5
    rel_slope = slope / avg_price * 1000  # scaled
    # sigmoid to 0-1
    return 1.0 / (1.0 + math.exp(-rel_slope))