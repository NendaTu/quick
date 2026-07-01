"""
Market Phase Recognition: Accumulation, Manipulation, Distribution

Identifies consolidation and expansion phases based on volatility, volume,
and structural divergences.

Identification:
- Accumulation: Low volatility (<30% ATR), high volume (>1.2x SMA), tight range.
- Manipulation: Post-accumulation sweep with sharp reversal.
- Distribution: Elevated volatility, high volume, failing to make new highs/lows.
"""

from typing import List, Dict, Optional
from ta.indicators.atr import compute_atr
from ta.utils import calculate_sma
from ta.patterns.sweep import detect_sweeps

# --- Internal Configuration ---
ENABLED = True
ACCUM_VOL_THRESH = 1.2
DIST_VOL_THRESH = 1.3
VOLATILITY_RATIO = 0.3 # <30% ATR means low vol

def identify_phases(ohlcv: List[dict]) -> Dict:
    """
    Categorizes the current market phase.
    """
    if not ENABLED or len(ohlcv) < 50:
        return {}

    relevant = ohlcv[-20:]
    highs = [c['h'] for c in relevant]
    lows = [c['l'] for c in relevant]
    closes = [c['c'] for c in relevant]
    volumes = [c['v'] for c in ohlcv]

    range_size = max(highs) - min(lows)
    atr = compute_atr(highs, lows, closes)
    avg_vol = calculate_sma(volumes[:-1], 50)
    curr_vol_avg = sum(v for v in volumes[-20:]) / 20

    phase = 'trending'

    # 1. Accumulation Check
    if range_size < (VOLATILITY_RATIO * atr) and curr_vol_avg > (ACCUM_VOL_THRESH * avg_vol):
        phase = 'accumulation'

    # 2. Distribution Check
    elif range_size > (0.5 * atr) and curr_vol_avg > (DIST_VOL_THRESH * avg_vol):
        # Check if failing to make progress (Simplified: close near range middle)
        range_mid = (max(highs) + min(lows)) / 2
        if abs(closes[-1] - range_mid) < (range_size * 0.2):
            phase = 'distribution'

    # 3. Manipulation Check
    sweep_data = detect_sweeps(ohlcv)
    if sweep_data.get('sweep_detected') and phase == 'accumulation':
        phase = 'manipulation'

    return {
        'market_phase': phase,
        'is_consolidating': phase in ['accumulation', 'distribution']
    }

def get_signal(ohlcv, tf, params=None, **kwargs):
    """
    Backtestable interface for Phases.
    Triggers LONG on Manipulation, SHORT on Distribution.
    """
    phase_data = identify_phases(ohlcv)
    phase = phase_data.get('market_phase')

    if phase not in ['manipulation', 'distribution']:
        return None

    price = ohlcv[-1]['c']
    atr = compute_atr([c['h'] for c in ohlcv], [c['l'] for c in ohlcv], [c['c'] for c in ohlcv])
    if atr == 0: atr = price * 0.01

    if phase == 'manipulation':
        return {
            "side": "long",
            "entry_price": price,
            "stop_price": price - atr,
            "exit_price": price + (atr * 2)
        }
    if phase == 'distribution':
        return {
            "side": "short",
            "entry_price": price,
            "stop_price": price + atr,
            "exit_price": price - (atr * 2)
        }
    return None
