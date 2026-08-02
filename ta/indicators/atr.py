"""
> ta/indicators/atr.py

1. Summary: Average True Range (ATR) volatility series calculator.
2. Description: Measures and reports market volatility using rolling ATR
   calculations. Strictly analysis/reporting -- this module does not decide
   risk policy (position sizing, stop distance, or risk reduction) from the
   volatility it measures; that belongs to config.py / tools/trading_utils.py
   and the strategies that consume ATR values, not to this file. Four
   constants that used to do exactly that -- SL_MULT, MIN_VOLATILITY,
   VOL_ADJUST_THRESHOLD, REDUCED_RISK_FRACTION -- were removed here on
   8/1/2026 as unused dead config; see atr-risk-constants-findings.md for
   the per-constant evidence. Two are confirmed still-needed and NOT yet
   wired up anywhere: config.py's USE_VOL_ADJUSTED_RISK toggle has no
   effect without VOL_ADJUST_THRESHOLD/REDUCED_RISK_FRACTION behind it, and
   ta/scoring.py's ScoringEngine reads config_context.MIN_VOLATILITY via
   getattr() but nothing defines it in config.py, so it's silently using
   its own fallback instead.
3. Context: Imported by strategies and features layers. get_signal() is also
   a stateless entry point usable directly, or as a non-directional filter
   segment inside backtest.py's ConfluenceChain (which treats "side": "both"
   as "matches regardless of the other segments' direction" -- see
   ConfluenceChain.check()).

Audited by Claude on 8/1/2026
"""
from typing import List, Dict, Optional

from ta.helpers.params import resolve

# --- Configuration ---
# Toggle to enable/disable ATR calculation.
ENABLED = True

# Standard period for ATR calculation (default: 14).
# Higher values result in a smoother, more stable volatility estimate.
PERIOD = 14
TF_PERIODS = {
    '1m': 21,  # Smoother for noise
    '5m': 14,
    '1H': 10,  # Faster for HTF
    '1D': 7
}

# Default Strategy Settings
DEFAULT_THRESHOLD_PCT = 0.15 # 0.15%


def get_signal(ohlcv, tf, params=None, **kwargs) -> Optional[Dict]:
    """
    Backtesting entry point: reports current ATR volatility, gated by a
    minimum ATR% threshold. Non-directional -- returns "side": "both" so
    ConfluenceChain treats it as a filter rather than a direction to match.

    params (list; see backtest.py's StrategyWrapper/parse_confluence_command
    -- CLI-style args split on whitespace, so always strings here):
        params[0]: threshold_pct override (min ATR%% of price required to report)
        params[1]: period override (candles used in the ATR calculation)
    Both optional. Resolution order for each is params override > local
    default (there's no config.py equivalent for either yet, so the config
    tier is skipped here) -- see ta/helpers/params.resolve(). period's local
    default is timeframe-adaptive via TF_PERIODS when `tf` is known.
    """
    period_raw = resolve(params, "period", TF_PERIODS.get(tf, PERIOD) if tf else PERIOD, list_index=1)
    try:
        period = int(float(period_raw))
    except (TypeError, ValueError):
        return None
    if period <= 0:
        return None

    if len(ohlcv) < period + 2:
        return None

    threshold_raw = resolve(params, "threshold_pct", DEFAULT_THRESHOLD_PCT, list_index=0)
    try:
        threshold_pct = float(threshold_raw)
    except (TypeError, ValueError):
        return None

    h = [c['h'] for c in ohlcv]
    l = [c['l'] for c in ohlcv]
    cl = [c['c'] for c in ohlcv]

    atr_val = compute_atr(h, l, cl, period)
    curr_price = cl[-1]

    actual_pct = (atr_val / curr_price) * 100 if curr_price > 0 else 0

    if actual_pct < threshold_pct:
        return None

    return {
        "side": "both",
        "entry_price": curr_price,
        "stop_price": 0, # Not used for filter
        "exit_price": 0, # Not used for filter
        "metadata": {
            "atr": atr_val,
            "atr_pct": actual_pct,
            "period": period,
            "threshold_pct": threshold_pct,
        }
    }

def compute_atr(highs: List[float], lows: List[float], closes: List[float], period: int = None, timeframe: str = None) -> float:
    """
    Calculates the Average True Range.
    Uses Wilder's Smoothing for more stable volatility estimation.
    """
    if period is None:
        period = TF_PERIODS.get(timeframe, PERIOD) if timeframe else PERIOD

    if not ENABLED or period <= 0 or len(closes) < period + 1:
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
    Dynamic Volatility Scaling: Compares ST-ATR vs LT-ATR.
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

def is_expansion_candle(ohlcv: List[dict], multiplier: float, period: int = None, timeframe: str = None) -> Dict:
    """
    Checks if the most recently closed candle is an 'Expansion Candle'.
    An expansion candle is defined as having a range (H-L) that exceeds
    the ATR of the preceding period by a specific multiplier.
    """
    # Standard Wilder's ATR needs period + 1 candles
    check_period = period if period else (TF_PERIODS.get(timeframe, PERIOD) if timeframe else PERIOD)

    if len(ohlcv) < check_period + 2:
        return {'is_expansion': False}

    # Use the last CLOSED candle for detection
    target_c = ohlcv[-2]

    # Calculate ATR of the candles PRECEDING the target candle
    # ohlcv[-1] is live candle, ohlcv[-2] is the one we check, ohlcv[:-2] is history
    preceding_ohlcv = ohlcv[:-2]

    h = [c['h'] for c in preceding_ohlcv]
    l = [c['l'] for c in preceding_ohlcv]
    c = [c['c'] for c in preceding_ohlcv]

    atr_val = compute_atr(h, l, c, check_period)
    if atr_val <= 0:
        return {'is_expansion': False}

    target_range = target_c['h'] - target_c['l']
    is_expansion = target_range > (atr_val * multiplier)

    return {
        'is_expansion': is_expansion,
        'candle': target_c,
        'range': target_range,
        'atr': atr_val,
        'ratio': target_range / atr_val if atr_val > 0 else 0
    }
