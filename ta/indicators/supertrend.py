"""
Supertrend Strategy

How it works:
1. This is a "Trailing" trend-following strategy that uses Average True Range (ATR)
   to account for market volatility.
2. It plots a line (the "Supertrend") above or below the price.
3. Signal Logic:
   - Buy: Triggered the moment the trend flips from Bearish to Bullish (Price closes above the top line).
   - Sell: Triggered the moment the trend flips from Bullish to Bearish (Price closes below the bottom line).
4. Stop Loss (SL): Placed at the next local swing point (valley for Longs, peak for Shorts)
   to provide a safe buffer beyond the immediate trend line.
5. Take Profit (TP): Targets a specific net profit (default +1% ROE).
6. Backtesting command: `python backtest.py supertrend [period] [multiplier] [rrr_override]`
"""

from typing import List, Tuple, Dict, Optional
from ta.indicators.atr import compute_atr
from ta.patterns.swings import detect_swings
from tools.trading_utils import calculate_tp_for_roe, calculate_target_roe_for_rrr
import config

# --- Configuration ---
ENABLED = True
PERIOD = 10
MULTIPLIER = 3.0

# Default Strategy Settings
DEFAULT_TARGET_ROE = 0.01

def get_signal(ohlcv: List[dict], timeframe: str, params: List[str] = None) -> Optional[Dict]:
    """
    Backtesting entry point for Supertrend strategy.
    """
    if len(ohlcv) < PERIOD + 5:
        return None

    # Parse Parameters
    period = int(params[0]) if params and len(params) > 0 else PERIOD
    mult = float(params[1]) if params and len(params) > 1 else MULTIPLIER
    rrr_override = float(params[2]) if params and len(params) > 2 else None

    # 1. Calculate trend for current and previous candle
    h = [c['h'] for c in ohlcv]
    l = [c['l'] for c in ohlcv]
    c = [c['c'] for c in ohlcv]

    _, current_dir = compute_supertrend(h, l, c, period, mult)
    _, prev_dir = compute_supertrend(h[:-1], l[:-1], c[:-1], period, mult)

    entry_side = None

    # 2. Bullish Signal: Flip from -1 to 1
    if prev_dir == -1 and current_dir == 1:
        entry_side = "buy"
    # Bearish Signal: Flip from 1 to -1
    elif prev_dir == 1 and current_dir == -1:
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
        "metadata": {"supertrend_dir": current_dir}
    }

def compute_supertrend(highs: List[float], lows: List[float], closes: List[float], period: int = None, multiplier: float = None) -> Tuple[float, int]:
    """
    Full Supertrend implementation.
    Returns (trend_value, direction) where direction is 1 for bullish, -1 for bearish.
    """
    if period is None: period = PERIOD
    if multiplier is None: multiplier = MULTIPLIER

    if not ENABLED or len(closes) < period + 1:
        return closes[-1] if closes else 0.0, 1

    atr = compute_atr(highs, lows, closes, period)

    # Simplified state tracking based on last two bars for stateless call compatibility
    curr_upper_band = (highs[-1] + lows[-1]) / 2 + (multiplier * atr)
    curr_lower_band = (highs[-1] + lows[-1]) / 2 - (multiplier * atr)

    prev_atr = compute_atr(highs[:-1], lows[:-1], closes[:-1], period)
    prev_upper_band = (highs[-2] + lows[-2]) / 2 + (multiplier * prev_atr)
    prev_lower_band = (highs[-2] + lows[-2]) / 2 - (multiplier * prev_atr)

    # Adjustment logic to prevent band widening
    if not (curr_upper_band < prev_upper_band or closes[-2] > prev_upper_band):
        curr_upper_band = prev_upper_band

    if not (curr_lower_band > prev_lower_band or closes[-2] < prev_lower_band):
        curr_lower_band = prev_lower_band

    # Trend logic
    if closes[-1] > prev_upper_band:
        trend = 1
    elif closes[-1] < prev_lower_band:
        trend = -1
    else:
        trend = 1 if closes[-1] > (curr_upper_band + curr_lower_band) / 2 else -1

    return (curr_lower_band if trend == 1 else curr_upper_band), trend
