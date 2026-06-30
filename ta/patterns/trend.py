"""
Trend and Bias Recognition Strategy

How it works:
1. This strategy identifies the "Main Trend" of the market by combining two methods:
   - Moving Averages: Comparing where the price is relative to the 50 and 200 Moving Averages.
   - Price Action Swings: Checking if the market is creating Higher Highs or Lower Lows.
2. A Bullish signal occurs when the price is above the 200 MA, the 50 MA is above the 200 MA,
   and recent swings are pointing upwards.
3. A Bearish signal occurs when the price is below the 200 MA, the 50 MA is below the 200 MA,
   and recent swings are pointing downwards.
4. Stop Loss (SL): Placed at the most recent "valley" (for Longs) or "peak" (for Shorts)
   to give the trade room to breathe while protecting the account.
5. Take Profit (TP): Targets a specific net profit (default +1% ROE).
6. Backtesting command: `python backtest.py trend [fast_ma] [slow_ma] [rrr_override]`
"""

from typing import List, Dict, Optional
from ta.patterns.swings import detect_swings
from ta.indicators.ema import compute_ema
from ta.utils import calculate_sma
from tools.trading_utils import calculate_tp_for_roe, calculate_target_roe_for_rrr
import config

# --- Configuration ---
# Toggle to enable/disable trend analysis.
ENABLED = True

# Standard periods for MA-based trend calculation.
SMA_FAST = 50
SMA_SLOW = 200

# If True, 'neutral' bias does not block entries.
NEUTRAL_ALLOWS_TRADES = True

# Default Strategy Settings
DEFAULT_FAST = 50
DEFAULT_SLOW = 200
DEFAULT_TARGET_ROE = 0.01

def get_signal(ohlcv: List[dict], timeframe: str, params: List[str] = None) -> Optional[Dict]:
    """
    Backtesting entry point for Trend strategy.
    """
    if len(ohlcv) < 200:
        return None

    # Parse Parameters
    fast_period = int(params[0]) if params and len(params) > 0 else DEFAULT_FAST
    slow_period = int(params[1]) if params and len(params) > 1 else DEFAULT_SLOW
    rrr_override = float(params[2]) if params and len(params) > 2 else None

    # 1. Gather Data
    trend_info = identify_trend(ohlcv)
    if not trend_info or trend_info['bias'] == 'neutral':
        return None

    bias = trend_info['bias']
    entry = ohlcv[-1]['c']

    # 2. Get Swings for Stop Loss
    swings = detect_swings(ohlcv[-100:], strength=2)
    if bias == 'bullish':
        if not swings['lows']: return None
        stop = swings['lows'][-1]['price']
    else: # bearish
        if not swings['highs']: return None
        stop = swings['highs'][-1]['price']

    if stop == entry: return None

    # 3. Calculate TP
    entry_maker = (config.ENTRY_ORDER_TYPE == "limit")
    tp_maker = (config.TP_ORDER_TYPE == "limit")

    if rrr_override is not None:
        target_roe = calculate_target_roe_for_rrr(rrr_override, entry, stop, 20, entry_maker=entry_maker)
    else:
        target_roe = DEFAULT_TARGET_ROE

    tp = calculate_tp_for_roe(entry, target_roe, 'buy' if bias == 'bullish' else 'sell', 20, entry_maker=entry_maker, exit_maker=tp_maker)

    return {
        "side": 'buy' if bias == 'bullish' else 'sell',
        "entry_price": entry,
        "stop_price": stop,
        "exit_price": tp,
        "metadata": {"trend_ma": trend_info['trend_ma'], "trend_swing": trend_info['trend_swing']}
    }

def identify_trend(ohlcv: List[dict], htf_ohlcv: Optional[List[dict]] = None) -> Dict:
    """
    Determines overall market trend and bias.
    """
    if not ENABLED or len(ohlcv) < 200:
        return {}

    closes = [c['c'] for c in ohlcv]
    current_price = closes[-1]

    sma_50 = calculate_sma(closes, SMA_FAST)
    sma_200 = calculate_sma(closes, SMA_SLOW)

    ma_trend = 'sideways'
    if current_price > sma_200 and sma_50 > sma_200:
        ma_trend = 'bullish'
    elif current_price < sma_200 and sma_50 < sma_200:
        ma_trend = 'bearish'

    swings = detect_swings(ohlcv[-100:], strength=2)
    highs = swings['highs']
    lows = swings['lows']

    swing_trend = 'neutral'
    if len(highs) >= 2 and len(lows) >= 2:
        if highs[-1]['price'] > highs[-2]['price'] and lows[-1]['price'] > lows[-2]['price']:
            swing_trend = 'bullish'
        elif highs[-1]['price'] < highs[-2]['price'] and lows[-1]['price'] < lows[-2]['price']:
            swing_trend = 'bearish'

    bias = 0
    if htf_ohlcv and len(htf_ohlcv) > 50:
        htf_closes = [c['c'] for c in htf_ohlcv]
        htf_ema = compute_ema(htf_closes, 20)
        if htf_closes[-1] > htf_ema: bias += 1
        else: bias -= 1

    if ma_trend == 'bullish': bias += 1
    elif ma_trend == 'bearish': bias -= 1

    if swing_trend == 'bullish': bias += 1
    elif swing_trend == 'bearish': bias -= 1

    return {
        'trend_ma': ma_trend,
        'trend_swing': swing_trend,
        'bias_score': bias,
        'bias': 'bullish' if bias > 0 else 'bearish' if bias < 0 else 'neutral'
    }
