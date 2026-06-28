"""
Liquidity Sweep Pattern Recognition

Detects moves that briefly exceed known BSL/SSL levels then reverse,
trapping breakout traders.

Identification:
- Buy-side sweep: High > BSL then Close < BSL.
- Sell-side sweep: Low < SSL then Close > SSL.
- Confirmation: Followed by strong reversal candle within 1-3 bars.
"""

from typing import List, Dict, Optional
from ta.patterns.liquidity import identify_liquidity

# --- Internal Configuration ---
ENABLED = True
CONFIRMATION_BARS = 3
SWEEP_MARGIN_PCT = 0.002 # 0.2% minimum break to avoid noise

def detect_sweeps(ohlcv: List[dict]) -> Dict:
    """
    Checks for recent liquidity sweeps.
    """
    if not ENABLED or len(ohlcv) < 50:
        return {}

    # Identify liquidity pools based on preceding data (exclude current bar)
    liquidity = identify_liquidity(ohlcv[:-1], lookback=50)
    if not liquidity:
        return {}

    bsl = liquidity['bsl_level']
    ssl = liquidity['ssl_level']

    last = ohlcv[-1]
    prev = ohlcv[-2]

    sweep_type = None

    # 1. Buy Side Sweep (Liquidity Hunt)
    if last['h'] > bsl and last['c'] < bsl:
        # Check for reversal confirmation (bearish engulfing or similar)
        if last['c'] < last['o']: # Bearish close
            sweep_type = 'buy_side'

    # 2. Sell Side Sweep
    elif last['l'] < ssl and last['c'] > ssl:
        if last['c'] > last['o']: # Bullish close
            sweep_type = 'sell_side'

    return {
        'sweep_detected': sweep_type is not None,
        'sweep_type': sweep_type,
        'sweep_level': bsl if sweep_type == 'buy_side' else (ssl if sweep_type == 'sell_side' else None)
    }
