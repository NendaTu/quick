"""
1. Summary: Abstract specification interface for simple technical strategies.
2. Description: Defines expected signature for get_signal() on historical candles data.
3. Context: Provides contract definitions for lightweight modular signal detectors.
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
