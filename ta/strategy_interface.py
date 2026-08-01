"""
> ta/strategy_interface.py

1. Summary: Abstract specification interface for stateless technical
   analysis modules.
2. Description: Defines the expected signature and return shape for
   detect() on historical candle data. Analysis modules identify patterns;
   they do not construct trades. Entry/stop/exit prices, order types, fees,
   and leverage do not belong in this contract or in anything implementing
   it -- that is strategy-layer responsibility, entirely outside ta/.
3. Context: Provides contract definitions for lightweight, stateless
   pattern detectors under ta/. [Revised 2026-07-31] The previous version
   of this contract (get_signal, returning entry_price/stop_price/
   exit_price) had ta/ modules implicitly deciding trade economics -- target
   ROE, leverage, maker/taker fee assumptions -- they have no business
   deciding. See ta/candles/engulfing.py's audit history for the case that
   surfaced this. ta/candles/engulfing_total.py (and possibly
   ta/candles/sentiment.py, unverified) still implement the old contract as
   of this revision -- pending a separate pass.

Audited by Claude on 8/1/2026
"""

from typing import Dict, List, Optional


def detect(
    ohlcv: List[Dict[str, float]],
    timeframe: str,
    params: Optional[Dict] = None,
    **kwargs,
) -> Optional[Dict]:
    """
    Standard interface for stateless ta/ analysis modules.

    Args:
        ohlcv: List of candle dictionaries {ts, o, h, l, c, v}
        timeframe: The timeframe being analyzed (e.g., '1m', '5m')
        params: Optional per-call overrides for analysis-level tunables
            only (e.g. a lookback window, a strictness threshold) -- never
            trade-construction values (target ROE, leverage, stop buffers,
            order type). Those don't belong here.
            [HELPERS-001, see ta/helpers/params.py] The exact shape this
            arrives in from real callers has not been confirmed -- treated
            as dict-like by convention until verified.

    Returns:
        A dictionary if a pattern is found, else None:
        {
            "side": "buy" | "sell",  # directional bias implied by the pattern
            "metadata": Dict,        # pattern type and other analysis facts
        }
        Deliberately excludes entry/stop/exit prices and anything
        order-type or fee related. Constructing a trade from a detected
        pattern is strategy-layer work, not ta/'s.
    """
    raise NotImplementedError("Analysis module must implement detect")
