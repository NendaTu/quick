"""
Statistical Arbitrage (Spread Divergence) Detection

Identifies tradeable divergences between highly correlated asset pairs.
"""
from typing import List, Dict, Optional
import logging

log = logging.getLogger("scalper.ta.spread")

# --- Configuration ---
ENABLED = True

# Z-Score threshold to trigger a mean-reversion trade.
Z_THRESHOLD = 2.0

def detect_divergence(asset1_ohlcv: List[dict], asset2_ohlcv: List[dict], correlation: float) -> Dict:
    """
    Calculates the spread z-score between two assets.
    """
    if not ENABLED or correlation < 0.8 or len(asset1_ohlcv) < 20 or len(asset2_ohlcv) < 20:
        return {'divergence_active': False}

    # Normalize prices (Percent change from start of window)
    p1 = [c['c'] for c in asset1_ohlcv[-20:]]
    p2 = [c['c'] for c in asset2_ohlcv[-20:]]

    n1 = [x / p1[0] for x in p1]
    n2 = [x / p2[0] for x in p2]

    spread = [a - b for a, b in zip(n1, n2)]

    avg_spread = sum(spread) / len(spread)
    std_spread = (sum((x - avg_spread)**2 for x in spread) / len(spread))**0.5

    current_spread = spread[-1]
    z_score = (current_spread - avg_spread) / (std_spread + 1e-9)

    active = abs(z_score) > Z_THRESHOLD

    return {
        'divergence_active': active,
        'z_score': z_score,
        'recommended_side': 'sell' if z_score > 0 else 'buy' # Sell the outperformer, buy the underperformer
    }
