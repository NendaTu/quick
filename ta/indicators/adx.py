"""
1. Summary: Average Directional Index (ADX) trend strength calculator.
2. Description: Computes ADX and directional indicators (+DI, -DI) over rolling periods to measure macro trend strength.
3. Context: Imported by feature extraction modules to filter out weak-trending configurations.
"""
from typing import List, Tuple, Dict, Optional
from ta.indicators.atr import compute_atr

# --- Configuration ---
ENABLED = True
PERIOD = 14

# Threshold above which we consider the market strongly trending.
STRONG_TREND_THRESHOLD = 25.0

def get_signal(ohlcv, tf, params=None, **kwargs) -> Optional[Dict]:
    """
    Backtesting entry point for ADX Trend Strength filter.
    """
    if len(ohlcv) < PERIOD * 2 + 5:
        return None

    # Parse Parameters
    threshold = float(params[0]) if params and len(params) > 0 else STRONG_TREND_THRESHOLD

    h = [c['h'] for c in ohlcv]
    l = [c['l'] for c in ohlcv]
    c = [c['c'] for c in ohlcv]

    adx_val = compute_adx(h, l, c, PERIOD)

    if adx_val < threshold:
        return None

    return {
        "side": "both",
        "entry_price": ohlcv[-1]['c'],
        "stop_price": 0,
        "exit_price": 0,
        "metadata": {"adx": adx_val}
    }

def compute_adx(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
    """
    Calculates the ADX with proper smoothing.
    """
    if not ENABLED or len(closes) < period * 2:
        return 0.0

    # 1. Calculate TR, DM+ and DM-
    tr_series = []
    up_moves = []
    down_moves = []
    for i in range(1, len(closes)):
        tr = max(highs[i] - lows[i],
                 abs(highs[i] - closes[i - 1]),
                 abs(lows[i] - closes[i - 1]))
        tr_series.append(tr)

        up = highs[i] - highs[i-1]
        down = lows[i-1] - lows[i]

        if up > down and up > 0:
            up_moves.append(up)
        else:
            up_moves.append(0)

        if down > up and down > 0:
            down_moves.append(down)
        else:
            down_moves.append(0)

    # 2. Smooth TR, DM+ and DM- (Wilder's)
    atr = sum(tr_series[:period]) / period
    plus_dm_s = sum(up_moves[:period]) / period
    minus_dm_s = sum(down_moves[:period]) / period

    dx_series = []

    # Calculate DX for the series
    for i in range(period, len(tr_series)):
        atr = (atr * (period - 1) + tr_series[i]) / period
        plus_dm_s = (plus_dm_s * (period - 1) + up_moves[i]) / period
        minus_dm_s = (minus_dm_s * (period - 1) + down_moves[i]) / period

        if atr == 0:
            dx_series.append(0)
            continue

        plus_di = 100 * (plus_dm_s / atr)
        minus_di = 100 * (minus_dm_s / atr)

        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di) if (plus_di + minus_di) != 0 else 0
        dx_series.append(dx)

    if not dx_series:
        return 0.0

    # 3. Calculate ADX (SMA of DX)
    adx = sum(dx_series[-period:]) / period
    return adx
