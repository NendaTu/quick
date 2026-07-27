"""
1. Summary: Moving Average Convergence Divergence (MACD) oscillator.
2. Description: Computes MACD lines, signal curves, and hist slopes to spot momentum shifts and reversals.
3. Context: Used by the ScoringEngine as a heavy-weighted indicator of price momentum.
"""
from typing import List, Tuple, Dict, Optional
from ta.patterns.swings import detect_swings
from tools.trading_utils import calculate_tp_for_roe, calculate_target_roe_for_rrr
import config

# --- Configuration ---
ENABLED = True
FAST = 12
SLOW = 26
SIGNAL = 9

# Default Strategy Settings
DEFAULT_TARGET_ROE = 0.01

def get_signal(ohlcv, tf, params=None, **kwargs) -> Optional[Dict]:
    """
    Backtesting entry point for MACD strategy.
    """
    if len(ohlcv) < SLOW + 2:
        return None

    # Parse Parameters
    fast = int(params[0]) if params and len(params) > 0 else FAST
    slow = int(params[1]) if params and len(params) > 1 else SLOW
    sig_p = int(params[2]) if params and len(params) > 2 else SIGNAL
    rrr_override = float(params[3]) if params and len(params) > 3 else None

    # 1. Calculate MACD for current and previous candle
    prices = [c['c'] for c in ohlcv]
    _, _, current_hist = compute_macd(prices, fast, slow, sig_p)
    _, _, prev_hist = compute_macd(prices[:-1], fast, slow, sig_p)

    entry_side = None

    # 2. Bullish Signal: Histogram turns positive
    if prev_hist <= 0 and current_hist > 0:
        entry_side = "buy"
    # Bearish Signal: Histogram turns negative
    elif prev_hist >= 0 and current_hist < 0:
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
        "metadata": {"macd_hist": current_hist}
    }

def compute_macd(prices: List[float], fast: int = None, slow: int = None, signal: int = None) -> Tuple[float, float, float]:
    """Optimized MACD calculation."""
    if fast is None: fast = FAST
    if slow is None: slow = SLOW
    if signal is None: signal = SIGNAL

    if not ENABLED or len(prices) < slow:
        return 0.0, 0.0, 0.0

    k_fast = 2.0 / (fast + 1)
    k_slow = 2.0 / (slow + 1)
    k_signal = 2.0 / (signal + 1)

    ema_fast = sum(prices[:fast]) / fast
    ema_slow = sum(prices[:slow]) / slow
    start_idx = slow

    macd_series = []
    macd_series.append(ema_fast - ema_slow)

    for p in prices[start_idx:]:
        ema_fast = (p - ema_fast) * k_fast + ema_fast
        ema_slow = (p - ema_slow) * k_slow + ema_slow
        macd_series.append(ema_fast - ema_slow)

    if len(macd_series) < signal:
        ema_signal = sum(macd_series) / len(macd_series)
    else:
        ema_signal = sum(macd_series[:signal]) / signal
        for m in macd_series[signal:]:
            ema_signal = (m - ema_signal) * k_signal + ema_signal

    return macd_series[-1], ema_signal, macd_series[-1] - ema_signal
