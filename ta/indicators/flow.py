"""
Order Flow / Trade Delta Indicator
"""
from typing import List, Dict

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
