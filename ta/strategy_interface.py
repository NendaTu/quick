"""
TA Strategy Specification

This file defines the interface for 'backtestable' strategy files in the ta/ directory.
Files should implement the get_signal() function.
"""

from typing import List, Dict, Optional, Tuple

def get_signal(ohlcv, timeframe, params=None, **kwargs) -> Optional[Dict]:
    """
    Standard interface for TA strategies.

    Args:
        ohlcv: List of candle dictionaries {ts, o, h, l, c, v}
        timeframe: The timeframe being analyzed (e.g., '1m', '5m')
        params: Optional list of command-line arguments passed to the backtest

    Returns:
        A dictionary if a signal is found, else None:
        {
            "side": "buy" | "sell",
            "entry_price": float,
            "stop_price": float,
            "exit_price": Optional[float], # Target price for TP
            "metadata": Dict # Any extra info to log
        }
    """
    raise NotImplementedError("Strategy must implement get_signal")
