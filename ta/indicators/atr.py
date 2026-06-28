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
