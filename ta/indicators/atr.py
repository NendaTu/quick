"""
Average True Range (ATR) Indicator

Measures market volatility by decomposing the entire range of an asset price for that period.
"""
from typing import List

# --- Configuration ---
# Toggle to enable/disable ATR calculation.
ENABLED = True

# Standard period for ATR calculation (default: 14).
# Higher values result in a smoother, more stable volatility estimate.
PERIOD = 14

# --- Strategy Multipliers ---
# Standard multiplier for ATR-based stop losses.
# Distance = ATR * SL_MULT.
SL_MULT = 1.5

# Minimum absolute ATR value required to trade.
# Prevents the bot from entering "zombie" assets with zero volatility.
MIN_VOLATILITY = 0.0001

# --- Volatility Regime Thresholds ---
# ATR % level above which we consider the market "Too Volatile" and reduce risk.
VOL_ADJUST_THRESHOLD = 0.002 # 0.2% of price

# The fraction of RISK_PER_TRADE used when volatility exceeds VOL_ADJUST_THRESHOLD.
REDUCED_RISK_FRACTION = 0.5

def compute_atr(highs: List[float], lows: List[float], closes: List[float], period: int = None) -> float:
    """
    Calculates the Average True Range.
    Uses Wilder's Smoothing for more stable volatility estimation.
    """
    if period is None:
        period = PERIOD

    if not ENABLED or len(closes) < period + 1:
        return 0.0

    # 1. Calculate True Ranges
    tr_series = []
    for i in range(1, len(closes)):
        tr = max(highs[i] - lows[i],
                 abs(highs[i] - closes[i - 1]),
                 abs(lows[i] - closes[i - 1]))
        tr_series.append(tr)

    # 2. Initial Seed (SMA)
    atr = sum(tr_series[:period]) / period

    # 3. Recursive Smoothing (Wilder's)
    for tr in tr_series[period:]:
        atr = (atr * (period - 1) + tr) / period

    return atr

def detect_vol_regime(highs: List[float], lows: List[float], closes: List[float], period: int = None) -> str:
    """
    Classifies the current volatility regime based on ATR trend.
    Returns: 'Expansion', 'Contraction', or 'Stable'
    """
    if period is None:
        period = PERIOD

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

def get_volatility_forecast(highs: List[float], lows: List[float], closes: List[float]) -> str:
    """
    [OP-002] Dynamic Volatility Scaling: Compares ST-ATR vs LT-ATR.
    Returns: 'Expanding', 'Compressing', or 'Neutral'
    """
    if len(closes) < 51:
        return 'Neutral'

    st_atr = compute_atr(highs, lows, closes, 5)
    lt_atr = compute_atr(highs, lows, closes, 50)

    if st_atr > lt_atr * 1.15:
        return 'Expanding'
    elif st_atr < lt_atr * 0.85:
        return 'Compressing'
    else:
        return 'Neutral'
