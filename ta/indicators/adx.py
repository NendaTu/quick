"""
> ta/indicators/adx.py

1. Summary: Average Directional Index (ADX) trend strength calculator.
2. Description: Computes ADX, +DI and -DI over a rolling period using
   Wilder's smoothing applied consistently end-to-end (TR/+DM/-DM seeded
   then recursively smoothed, DX seeded then recursively smoothed into
   ADX itself) to measure macro trend strength and its dominant direction.
   Period can be fixed or resolved per-timeframe via TF_PERIODS, mirroring
   ta.indicators.atr. The trend-strength threshold is resolved through
   ta.helpers.params.resolve(), shared with the rest of ta/.
3. Context: Imported by feature extraction modules to filter out
   weak-trending configurations.

Audited by Claude on 8/1/2026
"""

from typing import List, Dict, NamedTuple, Optional
from ta.helpers.params import resolve

# --- Configuration ---
ENABLED = True
PERIOD = 14

# Timeframe -> period overrides, mirroring ta.indicators.atr.TF_PERIODS.
# Left empty: I couldn't re-fetch atr.py this session to confirm its exact
# keys/values (see chat), so nothing here yet. Any timeframe not present
# just falls back to PERIOD, so behavior is unchanged from before until
# this is populated with the real table.
TF_PERIODS: Dict[str, int] = {}

# Threshold above which we consider the market strongly trending.
STRONG_TREND_THRESHOLD = 25.0


class ADXResult(NamedTuple):
    """ADX plus the directional components it's derived from."""
    adx: float
    plus_di: float
    minus_di: float


def _resolve_period(period: Optional[int], timeframe: Optional[str]) -> int:
    """An explicit `period` always wins. Otherwise resolve from TF_PERIODS
    by `timeframe`, falling back to the flat PERIOD constant."""
    if period is not None:
        return period
    return TF_PERIODS.get(timeframe, PERIOD) if timeframe else PERIOD


def _params_as_mapping(params, key):
    """
    Bridges this module's established params shape with resolve()'s
    dict-like `.get()` expectation.

    ta/helpers/params.py's own [HELPERS-001] note flags that params' real
    shape (list vs dict) is unconfirmed anywhere in this codebase --
    ta/strategy_interface.py documents it as a list, and no live caller of
    any ta/*.get_signal() could be found (ta/features.py and
    strategies/base_strategy.py were already checked per params.py's own
    docstring; I additionally checked engine/core.py's trading loop, which
    calls strategy.get_entry_signal() and ScoringEngine.evaluate()
    directly, never a ta/ module's get_signal()). What IS confirmed is
    this module's own tested contract: params[0] as the sole positional
    threshold override. Passing a raw list straight into resolve() would
    silently defeat that (lists have no .get, so resolve() reads it as
    "nothing supplied" and falls through to config/local_default) -- so
    this normalizes list/tuple -> dict to keep the existing, tested
    override path working, while passing an already dict-like params
    through untouched in case the real shape is (or becomes) dict-based.
    """
    if params is None:
        return None
    if hasattr(params, "get"):
        return params
    if isinstance(params, (list, tuple)) and len(params) > 0:
        return {key: params[0]}
    return None


def get_signal(ohlcv: List[Dict], tf: str, params: Optional[list] = None, **kwargs) -> Optional[Dict]:
    """
    Backtesting entry point for the ADX Trend Strength filter.

    Non-directional filter: returns a signal once ADX >= threshold.
    Threshold resolution goes through ta.helpers.params.resolve():
    params override > config attribute (none defined for ADX yet, see
    chat) > STRONG_TREND_THRESHOLD. "side" is always "both" and
    stop_price/exit_price are 0, since this indicator doesn't propose
    trade levels (matches the convention in ta.indicators.atr.get_signal).
    metadata carries adx, plus_di and minus_di so callers can see which
    direction is currently dominant. Period is resolved from `tf` via
    TF_PERIODS when possible.
    """
    period = _resolve_period(None, tf)
    if len(ohlcv) < period * 2 + 1:
        return None

    threshold = float(resolve(
        params=_params_as_mapping(params, "threshold"),
        key="threshold",
        local_default=STRONG_TREND_THRESHOLD,
        config_attr=None,  # no ADX-specific attribute exists in config.py yet
        config=None,
    ))

    h = [bar['h'] for bar in ohlcv]
    l = [bar['l'] for bar in ohlcv]
    c = [bar['c'] for bar in ohlcv]

    result = compute_adx_full(h, l, c, period=period)

    if result.adx < threshold:
        return None

    return {
        "side": "both",
        "entry_price": c[-1],
        "stop_price": 0,   # Not used for filter
        "exit_price": 0,   # Not used for filter
        "metadata": {
            "adx": result.adx,
            "plus_di": result.plus_di,
            "minus_di": result.minus_di,
        }
    }


def compute_adx(highs: List[float], lows: List[float], closes: List[float],
                 period: Optional[int] = None, timeframe: Optional[str] = None) -> float:
    """Thin wrapper over compute_adx_full for callers that only need the ADX scalar."""
    return compute_adx_full(highs, lows, closes, period, timeframe).adx


def compute_adx_full(highs: List[float], lows: List[float], closes: List[float],
                      period: Optional[int] = None, timeframe: Optional[str] = None) -> ADXResult:
    """
    Calculates ADX, +DI and -DI using Wilder's smoothing applied end-to-end.

    TR / +DM / -DM are seeded with a simple average over the first
    `period` bars, then recursively smoothed:
        value = (prev * (period - 1) + new) / period
    +DI/-DI/DX are derived from those at every step. ADX is seeded and
    recursively smoothed the exact same way -- a plain SMA of only the
    trailing DX window is NOT equivalent to this and will drift from
    standard ADX.

    `period` takes precedence if given; otherwise it's resolved from
    `timeframe` via TF_PERIODS (falling back to PERIOD).

    Runs as a single pass with O(1) extra memory (no per-bar lists).
    Requires at least period*2 + 1 closes; returns an all-zero result
    otherwise.
    """
    period = _resolve_period(period, timeframe)
    n = len(closes)
    if not ENABLED or period < 1 or n < period * 2 + 1:
        return ADXResult(0.0, 0.0, 0.0)

    # Phase 1: seed TR / +DM / -DM Wilder averages over the first `period` bars.
    tr_sum = plus_dm_sum = minus_dm_sum = 0.0
    for i in range(1, period + 1):
        h, ph, lo, plo, pc = highs[i], highs[i - 1], lows[i], lows[i - 1], closes[i - 1]
        tr_sum += max(h - lo, abs(h - pc), abs(lo - pc))
        up = h - ph
        down = plo - lo
        if up > down and up > 0:
            plus_dm_sum += up
        if down > up and down > 0:
            minus_dm_sum += down

    atr = tr_sum / period
    plus_dm_s = plus_dm_sum / period
    minus_dm_s = minus_dm_sum / period
    pm1 = period - 1
    plus_di = minus_di = 0.0

    # Phase 2: continue smoothing through the next `period` bars while
    # accumulating DX, to seed the ADX average itself.
    dx_sum = 0.0
    for i in range(period + 1, 2 * period + 1):
        h, ph, lo, plo, pc = highs[i], highs[i - 1], lows[i], lows[i - 1], closes[i - 1]
        tr = max(h - lo, abs(h - pc), abs(lo - pc))
        up = h - ph
        down = plo - lo
        plus_dm = up if (up > down and up > 0) else 0.0
        minus_dm = down if (down > up and down > 0) else 0.0

        atr = (atr * pm1 + tr) / period
        plus_dm_s = (plus_dm_s * pm1 + plus_dm) / period
        minus_dm_s = (minus_dm_s * pm1 + minus_dm) / period

        if atr != 0:
            plus_di = 100 * (plus_dm_s / atr)
            minus_di = 100 * (minus_dm_s / atr)
            di_sum = plus_di + minus_di
            dx = 100 * abs(plus_di - minus_di) / di_sum if di_sum != 0 else 0.0
        else:
            plus_di = minus_di = dx = 0.0
        dx_sum += dx

    adx = dx_sum / period

    # Phase 3: keep recursively smoothing ADX (and tracking +DI/-DI) the
    # same way TR/+DM/-DM are smoothed, for any bars beyond the seed window.
    for i in range(2 * period + 1, n):
        h, ph, lo, plo, pc = highs[i], highs[i - 1], lows[i], lows[i - 1], closes[i - 1]
        tr = max(h - lo, abs(h - pc), abs(lo - pc))
        up = h - ph
        down = plo - lo
        plus_dm = up if (up > down and up > 0) else 0.0
        minus_dm = down if (down > up and down > 0) else 0.0

        atr = (atr * pm1 + tr) / period
        plus_dm_s = (plus_dm_s * pm1 + plus_dm) / period
        minus_dm_s = (minus_dm_s * pm1 + minus_dm) / period

        if atr != 0:
            plus_di = 100 * (plus_dm_s / atr)
            minus_di = 100 * (minus_dm_s / atr)
            di_sum = plus_di + minus_di
            dx = 100 * abs(plus_di - minus_di) / di_sum if di_sum != 0 else 0.0
        else:
            plus_di = minus_di = dx = 0.0

        adx = (adx * pm1 + dx) / period

    return ADXResult(adx=adx, plus_di=plus_di, minus_di=minus_di)
