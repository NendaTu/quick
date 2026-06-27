"""
Supertrend Indicator
"""
from typing import List, Tuple
from ta.indicators.atr import compute_atr

# --- Configuration ---
ENABLED = True

def compute_supertrend(highs: List[float], lows: List[float], closes: List[float], period: int = 10, multiplier: float = 3.0) -> Tuple[float, int]:
    """
    Full Supertrend implementation.
    Returns (trend_value, direction) where direction is 1 for bullish, -1 for bearish.
    """
    if not ENABLED or len(closes) < period + 1:
        return closes[-1] if closes else 0.0, 1

    atr = compute_atr(highs, lows, closes, period)

    # Simplified state tracking based on last two bars for stateless call compatibility
    curr_upper_band = (highs[-1] + lows[-1]) / 2 + (multiplier * atr)
    curr_lower_band = (highs[-1] + lows[-1]) / 2 - (multiplier * atr)

    prev_atr = compute_atr(highs[:-1], lows[:-1], closes[:-1], period)
    prev_upper_band = (highs[-2] + lows[-2]) / 2 + (multiplier * prev_atr)
    prev_lower_band = (highs[-2] + lows[-2]) / 2 - (multiplier * prev_atr)

    # Adjustment logic to prevent band widening
    if not (curr_upper_band < prev_upper_band or closes[-2] > prev_upper_band):
        curr_upper_band = prev_upper_band

    if not (curr_lower_band > prev_lower_band or closes[-2] < prev_lower_band):
        curr_lower_band = prev_lower_band

    # Trend logic
    if closes[-1] > prev_upper_band:
        trend = 1
    elif closes[-1] < prev_lower_band:
        trend = -1
    else:
        trend = 1 if closes[-1] > (curr_upper_band + curr_lower_band) / 2 else -1

    return (curr_lower_band if trend == 1 else curr_upper_band), trend
