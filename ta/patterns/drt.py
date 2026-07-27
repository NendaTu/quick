"""
1. Summary: Directional Trend (DRT) linear regression slope calculator.
2. Description: Performs linear regression on candle closes to calculate price velocity and acceleration curves.
3. Context: Extremely strong predictor evaluated with high weight by the ScoringEngine.
"""
import math
from typing import List, Dict, Optional
from ta.patterns.swings import detect_swings
from tools.trading_utils import calculate_tp_for_roe, calculate_target_roe_for_rrr
import config

# --- Configuration ---
# Toggle to enable/disable DRT calculation.
ENABLED = True

# Number of points used for the linear regression calculation.
PERIOD = 20

# Minimum trend offset from 0.5 required to consider the market "trending".
# Example: 0.1 means DRT must be < 0.4 or > 0.6.
STRENGTH_MIN = 0.1

# Default Strategy Settings
DEFAULT_THRESHOLD_OFFSET = 0.1 # 0.6 / 0.4
DEFAULT_TARGET_ROE = 0.01

def get_signal(ohlcv, tf, params=None, **kwargs) -> Optional[Dict]:
    """
    Backtesting entry point for DRT strategy.
    """
    if len(ohlcv) < PERIOD + 5:
        return None

    # Parse Parameters
    offset = float(params[0]) if params and len(params) > 0 else DEFAULT_THRESHOLD_OFFSET
    # Map offset to thresholds (e.g. 0.1 -> 0.6/0.4)
    upper_thresh = 0.5 + offset
    lower_thresh = 0.5 - offset

    period = int(params[1]) if params and len(params) > 1 else PERIOD
    rrr_override = float(params[2]) if params and len(params) > 2 else None

    # 1. Calculate DRT for current and previous candle
    prices = [c['c'] for c in ohlcv]
    current_drt = compute_drt(prices, period)
    prev_drt = compute_drt(prices[:-1], period)

    entry_side = None

    # 2. Bullish Signal: Rise above upper threshold
    if prev_drt <= upper_thresh and current_drt > upper_thresh:
        entry_side = "buy"
    # Bearish Signal: Fall below lower threshold
    elif prev_drt >= lower_thresh and current_drt < lower_thresh:
        entry_side = "sell"

    if not entry_side:
        return None

    # 3. Entry/Exit Calculations
    entry = ohlcv[-1]['c']
    swings = detect_swings(ohlcv[-50:], strength=2)

    if entry_side == 'buy':
        if not swings['lows']: return None
        stop = swings['lows'][-1]['price']
    else: # sell
        if not swings['highs']: return None
        stop = swings['highs'][-1]['price']

    if stop == entry: return None

    entry_maker = (config.ENTRY_ORDER_TYPE == "limit")
    tp_maker = (config.TP_ORDER_TYPE == "limit")

    if rrr_override is not None:
        target_roe = calculate_target_roe_for_rrr(rrr_override, entry, stop, 20, entry_maker=entry_maker)
    else:
        target_roe = DEFAULT_TARGET_ROE

    tp = calculate_tp_for_roe(entry, target_roe, entry_side, 20, entry_maker=entry_maker, exit_maker=tp_maker)

    return {
        "side": entry_side,
        "entry_price": entry,
        "stop_price": stop,
        "exit_price": tp,
        "metadata": {"current_drt": current_drt}
    }

def compute_drt(prices: List[float], period: int = None) -> float:
    """Directional Trend 0-1: sigmoid of the slope of linear regression."""
    if period is None:
        period = PERIOD

    if not ENABLED or len(prices) < period:
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
    # Scaled for sensitivity: relative slope * 1000
    rel_slope = slope / avg_price * 1000
    return 1.0 / (1.0 + math.exp(-rel_slope))
