"""
Average True Range (ATR) Indicator
"""
from typing import List

# --- Configuration ---
ENABLED = True

def compute_atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
    if not ENABLED or len(closes) < period + 1:
        return 0.0

    tr_sum = 0.0
    for i in range(len(closes) - period, len(closes)):
        tr = max(highs[i] - lows[i],
                 abs(highs[i] - closes[i - 1]),
                 abs(lows[i] - closes[i - 1]))
        tr_sum += tr
    return tr_sum / period

def detect_vol_regime(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> str:
    """
    Classifies the current volatility regime based on ATR trend.
    Returns: 'Expansion', 'Contraction', or 'Stable'
    """
    if len(closes) < period * 2:
        return 'Stable'

    # Get current ATR and ATR from previous window
    atr_now = compute_atr(highs, lows, closes, period)
    atr_prev = compute_atr(highs[:-period], lows[:-period], closes[:-period], period)

    if atr_now > atr_prev * 1.25:
        return 'Expansion'
    elif atr_now < atr_prev * 0.75:
        return 'Contraction'
    else:
        return 'Stable'
