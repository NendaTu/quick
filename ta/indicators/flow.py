"""
1. Summary: Order Flow and aggressive trade pressure analyzer.
2. Description: Monitors trade streams to compute aggregated buy and sell volume velocity changes.
3. Context: Used to identify active institutional interest blocks and volume surges.
"""
from typing import List, Dict

# --- Configuration ---
# Minimum order book imbalance (bid vs ask pressure) required to trade.
MIN_IMBALANCE = 0.033

# Minimum relative volume required compared to recent average.
VOL_PCT_MIN = 0.05

# Threshold for HTF trend confluence (e.g., 15m trend).
TREND_HTF_MIN = 0.0001

def compute_trade_delta(trades: List[Dict]) -> float:
    """
    Calculates net volume delta from a list of recent market trades.
    Returns a normalized value between -1.0 and 1.0.
    """
    if not trades:
        return 0.0

    buy_vol = sum(t['size'] for t in trades if t['side'] == 'buy')
    sell_vol = sum(t['size'] for t in trades if t['side'] == 'sell')
    total_vol = buy_vol + sell_vol

    if total_vol == 0:
        return 0.0

    return (buy_vol - sell_vol) / total_vol

def get_signal(ohlcv, tf, params=None, **kwargs):
    """
    Backtestable interface for Flow (aggregated trades).
    Note: Standard OHLCV does not contain trade-level delta.
    This remains as a placeholder for MTF/Live integration.
    """
    return None
