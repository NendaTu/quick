"""
Trend and Bias Recognition

Classifies market direction and provides a bias for setups.

Identification:
- Swing-based Trend: HH/HL sequence (Uptrend), LH/LL sequence (Downtrend).
- MA-based Trend: Price relative to 50/200 SMAs.
- ADX: Measures trend strength.
- Bias: Composite of HTF trend and LTF momentum.
"""

from typing import List, Dict, Optional
from ta.patterns.swings import detect_swings
from ta.indicators.ema import compute_ema
from ta.utils import calculate_sma

# --- Internal Configuration ---
ENABLED = True
SMA_FAST = 50
SMA_SLOW = 200
NEUTRAL_ALLOWS_TRADES = True  # If True, 'neutral' bias does not block entries.

def identify_trend(ohlcv: List[dict], htf_ohlcv: Optional[List[dict]] = None) -> Dict:
    """
    Determines overall market trend and bias.
    """
    if not ENABLED or len(ohlcv) < 200:
        return {}

    closes = [c['c'] for c in ohlcv]
    current_price = closes[-1]

    # 1. MA-based Trend
    sma_50 = calculate_sma(closes, SMA_FAST)
    sma_200 = calculate_sma(closes, SMA_SLOW)

    ma_trend = 'sideways'
    if current_price > sma_200 and sma_50 > sma_200:
        ma_trend = 'bullish'
    elif current_price < sma_200 and sma_50 < sma_200:
        ma_trend = 'bearish'

    # 2. Swing-based Trend
    swings = detect_swings(ohlcv[-100:], strength=2)
    highs = swings['highs']
    lows = swings['lows']

    swing_trend = 'neutral'
    if len(highs) >= 2 and len(lows) >= 2:
        if highs[-1]['price'] > highs[-2]['price'] and lows[-1]['price'] > lows[-2]['price']:
            swing_trend = 'bullish'
        elif highs[-1]['price'] < highs[-2]['price'] and lows[-1]['price'] < lows[-2]['price']:
            swing_trend = 'bearish'

    # 3. Bias (HTF Trend Integration)
    bias = 0 # 0 neutral, +1 bull, -1 bear
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
