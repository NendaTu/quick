"""
Average True Range (ATR) Strategy (Filter)

How it works:
1. This is a "Volatility Filter" strategy. It ensures that trades are only taken
   when the market has enough "life" (movement) to hit targets.
2. It calculates the ATR as a percentage of the current price.
3. Signal Logic:
   - Returns "both" (allowing any direction) if the ATR % is above the threshold.
   - Blocks signals if the market is too quiet (ATR below threshold).
4. Backtesting command: `python backtest.py "atr [threshold_pct] + [trigger]"`
   - Example: `"atr 0.2 + engulfing"` (Requires 0.2% minimum volatility).
"""

from typing import List, Dict, Optional
import config

# --- Configuration ---
# Toggle to enable/disable ATR calculation.
ENABLED = True

# Standard period for ATR calculation (default: 14).
# Higher values result in a smoother, more stable volatility estimate.
# [OP Roadmap] Adaptive periods per timeframe.
PERIOD = 14
TF_PERIODS = {
    '1m': 21,  # Smoother for noise
    '5m': 14,
    '1H': 10,  # Faster for HTF
    '1D': 7
}

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

# Default Strategy Settings
DEFAULT_THRESHOLD_PCT = 0.15 # 0.15%

def get_signal(ohlcv, tf, params=None, **kwargs) -> Optional[Dict]:
    """
    Backtesting entry point for ATR Volatility filter.
    """
    if len(ohlcv) < PERIOD + 2:
        return None

    # Parse Parameters
    threshold_pct = float(params[0]) if params and len(params) > 0 else DEFAULT_THRESHOLD_PCT

    h = [c['h'] for c in ohlcv]
    l = [c['l'] for c in ohlcv]
    c = [c['c'] for c in ohlcv]

    atr_val = compute_atr(h, l, c, PERIOD)
    curr_price = c[-1]

    actual_pct = (atr_val / curr_price) * 100 if curr_price > 0 else 0

    if actual_pct < threshold_pct:
        return None

    return {
        "side": "both",
        "entry_price": curr_price,
        "stop_price": 0, # Not used for filter
        "exit_price": 0, # Not used for filter
        "metadata": {"atr_pct": actual_pct}
    }

def compute_atr(highs: List[float], lows: List[float], closes: List[float], period: int = None, timeframe: str = None) -> float:
    """
    Calculates the Average True Range.
    Uses Wilder's Smoothing for more stable volatility estimation.
    """
    if period is None:
        period = TF_PERIODS.get(timeframe, PERIOD) if timeframe else PERIOD

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
