"""
1. Summary: Liquidity sweep and wick stop-hunt detector.
2. Description: Identifies candle wicks that pierce past local extremes but close back inside the range, signifying a stop hunt.
3. Context: The underlying technical foundation of all sweep strategies.
"""
from typing import List, Dict, Optional
from ta.patterns.liquidity import identify_liquidity
from tools.trading_utils import calculate_tp_for_roe, calculate_target_roe_for_rrr
import config

# --- Configuration ---
# Toggle to enable/disable sweep detection.
ENABLED = True

# Minimum break (%) required beyond the liquidity level, on the wick, before a
# poke through the level counts as a sweep. Filters out marginal/noise wicks.
SWEEP_MARGIN_PCT = 0.002

# Bars of prior history identify_liquidity scans (excluding the current/reversal
# bar) to locate the BSL/SSL levels being swept.
LIQUIDITY_LOOKBACK = 50

# Bars required in `ohlcv` to run detection at all: LIQUIDITY_LOOKBACK bars of
# history for identify_liquidity, plus the current (reversal) bar itself.
# get_signal and detect_sweeps both gate on this so the two can never disagree.
MIN_BARS_REQUIRED = LIQUIDITY_LOOKBACK + 1


def get_signal(ohlcv: List[dict], tf, params: Optional[list] = None, **kwargs) -> Optional[Dict]:
    """
    Backtesting entry point for Liquidity Sweep strategy.
    """
    if len(ohlcv) < MIN_BARS_REQUIRED:
        return None

    # Parse Parameters
    rrr_override = float(params[0]) if params and len(params) > 0 else None

    # Retrieve centralized trade management parameters from config
    sl_buffer_pct = getattr(config, "SL_TICK_BUFFER", 0.0001)
    default_leverage = getattr(config, "DEFAULT_LEVERAGE", 20)
    default_target_roe = getattr(config, "TARGET_NET_ROE", 0.01)

    # 1. Identify Sweeps
    sweep_info = detect_sweeps(ohlcv)
    if not sweep_info.get('sweep_detected'):
        return None

    sweep_type = sweep_info['sweep_type']
    curr = ohlcv[-1]

    # 2. Map Sweep to Trade Direction
    # Buy Side Sweep (broke high) -> Sell
    # Sell Side Sweep (broke low) -> Buy
    if sweep_type == 'buy_side':
        entry_side = "sell"
        stop = curr['h'] * (1 + sl_buffer_pct)
    else:  # sell_side
        entry_side = "buy"
        stop = curr['l'] * (1 - sl_buffer_pct)

    entry = curr['c']
    if stop == entry:
        return None

    # 3. Calculate TP
    entry_maker = (config.ENTRY_ORDER_TYPE == "limit")
    tp_maker = (config.TP_ORDER_TYPE == "limit")

    if rrr_override is not None:
        target_roe = calculate_target_roe_for_rrr(
            rrr_override, entry, stop, default_leverage, entry_maker=entry_maker
        )
    else:
        target_roe = default_target_roe

    tp = calculate_tp_for_roe(
        entry, target_roe, entry_side, default_leverage,
        entry_maker=entry_maker, exit_maker=tp_maker
    )

    return {
        "side": entry_side,
        "entry_price": entry,
        "stop_price": stop,
        "exit_price": tp,
        "metadata": {"sweep_type": sweep_type, "sweep_level": sweep_info['sweep_level']}
    }


def detect_sweeps(ohlcv: List[dict]) -> Dict:
    """
    Checks whether the most recently closed bar in `ohlcv` is a liquidity sweep.

    Always returns a fully-keyed dict (sweep_detected / sweep_type / sweep_level /
    sweep_timestamp) -- including on early exit -- so any caller in the engine or
    another strategy file can rely on the shape without special-casing `{}`.
    """
    no_sweep = {
        'sweep_detected': False,
        'sweep_type': None,
        'sweep_level': None,
        'sweep_timestamp': None,
    }

    if not ENABLED or len(ohlcv) < MIN_BARS_REQUIRED:
        return no_sweep

    # Identify liquidity pools based on preceding data (exclude current bar)
    liquidity = identify_liquidity(ohlcv[:-1], lookback=LIQUIDITY_LOOKBACK)
    if not liquidity:
        return no_sweep

    bsl = liquidity.get('bsl_level')
    ssl = liquidity.get('ssl_level')

    last = ohlcv[-1]
    sweep_type = None

    # 1. Buy Side Sweep (Liquidity Hunt): wick clears BSL by the minimum
    # margin, then closes back below it on a bearish candle.
    if bsl is not None and last['h'] > bsl * (1 + SWEEP_MARGIN_PCT) and last['c'] < bsl:
        if last['c'] < last['o']:  # Bearish close
            sweep_type = 'buy_side'

    # 2. Sell Side Sweep: wick clears SSL by the minimum margin, then closes
    # back above it on a bullish candle.
    # NOTE: this is a separate `if`, not `elif`. A wide-range bar can pierce
    # both BSL and SSL in one candle; chaining these on elif meant a failed
    # buy-side check (e.g. non-bearish close) silently skipped ever evaluating
    # a genuinely valid sell-side sweep on that same bar. A candle's close
    # can't be both above and below its own open at once, so at most one of
    # these two blocks can ever actually set sweep_type.
    if ssl is not None and last['l'] < ssl * (1 - SWEEP_MARGIN_PCT) and last['c'] > ssl:
        if last['c'] > last['o']:  # Bullish close
            sweep_type = 'sell_side'

    if sweep_type is None:
        return no_sweep

    return {
        'sweep_detected': True,
        'sweep_type': sweep_type,
        'sweep_level': bsl if sweep_type == 'buy_side' else ssl,
        'sweep_timestamp': last['ts'],
    }
