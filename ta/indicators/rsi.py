"""
Relative Strength Index (RSI) Strategy

How it works:
1. This is a "Mean Reversion" strategy. It identifies when the market has moved too far, too fast,
   and is likely to "snap back" to a normal range.
2. It uses two thresholds:
   - Oversold (Default 30): Price is very low.
   - Overbought (Default 70): Price is very high.
3. Signal Logic:
   - Buy: Triggered when the RSI was below the Oversold level but has now closed back above it.
   - Sell: Triggered when the RSI was above the Overbought level but has now closed back below it.
4. Stop Loss (SL): Placed at the recent local valley (for Longs) or peak (for Shorts).
5. Take Profit (TP): Targets a specific net profit (default +1% ROE).
6. Backtesting command: `python backtest.py rsi [oversold] [overbought] [rrr_override]`
"""

from typing import List, Dict, Optional
from ta.patterns.swings import detect_swings
from tools.trading_utils import calculate_tp_for_roe, calculate_target_roe_for_rrr
import config

# --- Configuration ---
# Toggle to enable/disable RSI calculation.
ENABLED = True

# Standard period for RSI calculation (default: 14).
# Higher values result in a smoother but more lagging indicator.
# [OP Roadmap] Adaptive periods per timeframe.
PERIOD = 14
TF_PERIODS = {
    '1m': 21,  # Smoother for noise
    '5m': 14,
    '15m': 14,
    '1H': 9,   # Faster for HTF turns
    '4H': 7,
    '1D': 7
}

# --- Strategy Thresholds ---
# RSI level below which we consider the asset oversold for scoring (+1 point).
LONG_THRESHOLD = 40.0

# RSI level above which we consider the asset overbought for scoring (-1 point).
SHORT_THRESHOLD = 60.0

# Aggressive entry floor used in Adaptive RSI mode.
# If DRT momentum is weak, we require RSI to be even lower to buy.
TIGHT_LONG = 25.0

# Aggressive entry ceiling used in Adaptive RSI mode.
# If DRT momentum is weak, we require RSI to be even higher to short.
TIGHT_SHORT = 75.0

# --- Momentum Rider Gates ---
# RSI level below which we trigger Momentum Rider (Long).
# Instead of blocking, we tighten stops and ride the parabolic move.
BUY_FLOOR = 15.0

# RSI level above which we trigger Momentum Rider (Short).
# Instead of blocking, we tighten stops and ride the parabolic move.
SHORT_CEILING = 80.0

# Default Strategy Settings
DEFAULT_OVERSOLD = 30.0
DEFAULT_OVERBOUGHT = 70.0
DEFAULT_TARGET_ROE = 0.01

def get_signal(ohlcv, tf, params=None, **kwargs) -> Optional[Dict]:
    """
    Backtesting entry point for RSI strategy.
    """
    if len(ohlcv) < PERIOD + 2:
        return None

    # Parse Parameters
    oversold = float(params[0]) if params and len(params) > 0 else DEFAULT_OVERSOLD
    overbought = float(params[1]) if params and len(params) > 1 else DEFAULT_OVERBOUGHT
    rrr_override = float(params[2]) if params and len(params) > 2 else None

    # 1. Calculate RSI for current and previous candle
    prices = [c['c'] for c in ohlcv]
    current_rsi = compute_rsi(prices)
    prev_rsi = compute_rsi(prices[:-1])

    entry_side = None

    # 2. Bullish Signal: Crossed ABOVE Oversold
    if prev_rsi < oversold and current_rsi >= oversold:
        entry_side = "buy"
    # Bearish Signal: Crossed BELOW Overbought
    elif prev_rsi > overbought and current_rsi <= overbought:
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
        "metadata": {"current_rsi": current_rsi, "prev_rsi": prev_rsi}
    }

def compute_rsi(prices: List[float], period: int = None, timeframe: str = None) -> float:
    """
    Calculates the Relative Strength Index.
    Uses Wilder's Smoothing for more reliable signals in high-frequency trading.
    """
    if period is None:
        period = TF_PERIODS.get(timeframe, PERIOD) if timeframe else PERIOD

    if not ENABLED or len(prices) < period + 1:
        return 50.0

    # 1. Initial Seed (SMA)
    gains = []
    losses = []
    for i in range(1, period + 1):
        diff = prices[i] - prices[i-1]
        gains.append(max(0, diff))
        losses.append(max(0, -diff))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    # 2. Recursive Smoothing (Wilder's)
    for i in range(period + 1, len(prices)):
        diff = prices[i] - prices[i-1]
        gain = max(0, diff)
        loss = max(0, -diff)

        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))
