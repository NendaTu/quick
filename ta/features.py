"""
Stateless Technical Analysis Feature Extraction Module

This module isolates all technical analysis calculations from the Simulator and Engine classes,
allowing any components (Live Exchange, Simulator, Backtest) to compute standard metrics
from raw OHLCV series, order book state, and trade history without inheriting execution state.
"""

import math
import logging
from typing import Dict, List, Optional
import config

import ta.indicators.rsi as rsi_ind
import ta.indicators.atr as atr_ind
import ta.indicators.macd as macd_ind
import ta.indicators.supertrend as st_ind
import ta.patterns.drt as drt_pat
import ta.patterns.fvg as fvg_pat

from ta.indicators.rsi import compute_rsi
from ta.indicators.atr import compute_atr, detect_vol_regime, get_volatility_forecast
from ta.indicators.ema import compute_ema
from ta.indicators.flow import compute_trade_delta
from ta.indicators.macd import compute_macd
from ta.indicators.supertrend import compute_supertrend
from ta.patterns.drt import compute_drt
from ta.patterns.fvg import detect_fvgs
from ta.patterns.liquidity import identify_liquidity
from ta.patterns.sweep import detect_sweeps
from ta.patterns.structure import identify_structure
from ta.patterns.ob import detect_order_blocks
from ta.patterns.idm import detect_idm
from ta.patterns.momentum import identify_momentum
from ta.patterns.sessions import identify_sessions
from ta.patterns.phases import identify_phases
from ta.patterns.sr import identify_sr
from ta.patterns.trend import identify_trend
from ta.patterns.poi import identify_pois
from ta.indicators.adx import compute_adx
from ta.indicators.book_delta import compute_imbalance_delta
from ta.patterns.volume_profile import identify_poc

log = logging.getLogger("ta.features")

def extract_features(
    symbol: str,
    ohlcv_data: Dict[str, List[dict]],
    book,
    trade_history_list: List[dict],
    confluence_history_data: Dict[str, List[float]],
    btc_confluence_cache: Dict[str, float],
    imb_history_list: List[float],
    mid_history_list: List[float]
) -> Dict[str, float]:
    """
    Computes all standard technical analysis features from provided stateless data pools.
    """
    if not book:
        return {}

    # 1. Real-time Order Book and Trade Flow metrics
    bid_vol, ask_vol = book.top_bid_ask_qty()
    total_vol = bid_vol + ask_vol
    current_imb = (bid_vol - ask_vol) / total_vol if total_vol > 0 else 0.0

    # Imbalance Delta
    imb_delta = compute_imbalance_delta(current_imb, imb_history_list)
    imb_history_list.append(current_imb)
    if len(imb_history_list) > 20:
        imb_history_list.pop(0)

    # Mid Price Slope
    mid = (book.best_bid + book.best_ask) / 2
    mid_slope = 0
    if len(mid_history_list) >= 5:
        mid_slope = (mid - mid_history_list[-5]) / 5
    mid_history_list.append(mid)
    if len(mid_history_list) > 10:
        mid_history_list.pop(0)

    # Trade Delta (Real-time Flow)
    trade_delta = compute_trade_delta(trade_history_list[-50:])

    spread = book.best_ask - book.best_bid
    vol_pct = min(1.0, total_vol / 4000.0)

    # Helpers to extract ohlc lists
    def get_ohlc(tf):
        h = ohlcv_data.get(tf, [])
        if not h:
            return [], [], []
        relevant = h[-(config.INDICATOR_PRICE_HISTORY + 50):]
        return [x["c"] for x in relevant], [x["h"] for x in relevant], [x["l"] for x in relevant]

    # Timeframe-based indicators
    c1, h1, l1 = get_ohlc("1m")
    rsi_val = compute_rsi(c1, timeframe="1m") if len(c1) > 25 else 50.0
    macd, macd_signal, macd_hist = compute_macd(c1) if len(c1) > 30 else (0, 0, 0)
    atr = compute_atr(h1, l1, c1, timeframe="1m") if len(c1) > 25 else 0.0
    vol_regime = detect_vol_regime(h1, l1, c1, atr_ind.PERIOD) if len(c1) > 30 else 'Stable'
    vol_forecast = get_volatility_forecast(h1, l1, c1) if len(c1) > 51 else 'Neutral'
    adx = compute_adx(h1, l1, c1) if len(c1) > 30 else 0.0

    h_active = ohlcv_data.get(config.ACTIVE_TIMEFRAME, [])
    poc = identify_poc(h_active) if h_active else 0.0
    supertrend_val, supertrend_dir = compute_supertrend(h1, l1, c1, st_ind.PERIOD, st_ind.MULTIPLIER) if len(c1) > 20 else (0, 0)

    # DRT Slow (15m) and Fast (5m)
    cs, _, _ = get_ohlc("15m")
    drt_slow = compute_drt(cs, drt_pat.PERIOD) if len(cs) >= 20 else 0.5

    cf, _, _ = get_ohlc("5m")
    drt_fast = compute_drt(cf, drt_pat.PERIOD) if len(cf) >= 20 else 0.5

    drt = compute_drt(c1, 20) if len(c1) >= 20 else 0.5

    # Pattern Recognition
    h_fvg = ohlcv_data.get(fvg_pat.TIMEFRAME, [])
    h_1D = ohlcv_data.get("1D", [])

    fvg_data = detect_fvgs(h_fvg, depth=fvg_pat.HISTORY_DEPTH) if h_fvg else {}
    liq_data = identify_liquidity(h_active) if h_active else {}
    sweep_data = detect_sweeps(h_active) if h_active else {}
    struct_data = identify_structure(h_active) if h_active else {}
    ob_data = detect_order_blocks(h_active) if h_active else {}
    idm_data = detect_idm(h_active) if h_active else {}
    mom_data = identify_momentum(h_active) if h_active else {}
    sess_data = identify_sessions(h_active) if h_active else {}
    phase_data = identify_phases(h_active) if h_active else {}
    sr_data = identify_sr(h_active) if h_active else {}
    trend_data = identify_trend(h_active, htf_ohlcv=h_1D) if h_active else {}

    poi_data = identify_pois(h_active, ob_data, fvg_data, liq_data, sess_data) if h_active else {}

    asset_changes = {}
    for tf in ["15m", "1H", "4H", "1D"]:
        h = confluence_history_data.get(tf, [])
        if len(h) >= 3:
            asset_changes[f"asset_{tf}"] = (h[-2] / h[-3] - 1)
        else:
            asset_changes[f"asset_{tf}"] = 0.0

    features = {
        "imbalance": current_imb,
        "imbalance_delta": imb_delta, # Compatibility alias
        "imb_delta": imb_delta,
        "mid_slope": mid_slope,
        "spread_pct": spread / mid if mid > 0 else 0,
        "mid": mid,
        "vol_pct": vol_pct,
        "rsi": rsi_val,
        "atr": atr,
        "vol_regime": vol_regime,
        "vol_forecast": vol_forecast,
        "trade_delta": trade_delta,
        "poc": poc,
        "macd": macd,
        "macd_signal": macd_signal,
        "macd_hist": macd_hist,
        "adx": adx,
        "drt": drt,
        "drt_slow": drt_slow,
        "drt_fast": drt_fast,
        "supertrend_dir": supertrend_dir,
        "supertrend": float(supertrend_dir) * 100.0,
        **fvg_data,
        **liq_data,
        **sweep_data,
        **struct_data,
        **ob_data,
        **idm_data,
        **mom_data,
        **sess_data,
        **phase_data,
        **sr_data,
        **trend_data,
        **poi_data,
        **btc_confluence_cache,
        **asset_changes,
    }

    return features
