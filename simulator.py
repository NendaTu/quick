import asyncio, time, logging, math, random
from typing import Dict, List, Tuple, Optional
from config import *
from orderbook import SimulatedOrderBook
import ta.indicators.rsi as rsi_ind
import ta.indicators.atr as atr_ind
import ta.indicators.macd as macd_ind
import ta.indicators.supertrend as st_ind
import ta.patterns.drt as drt_pat
import ta.patterns.fvg as fvg_pat
from tools.trading_utils import calculate_fees, calculate_pnl
from ta.indicators.rsi import compute_rsi
from ta.indicators.atr import compute_atr, detect_vol_regime
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
from ta.indicators.atr import get_volatility_forecast
from database import Database
from bitget_client import BitGetClient, BitGetWSClient

log = logging.getLogger("scalper.simulator")

class Simulator:
    def __init__(self, use_db=True):
        self.books: Dict[str, SimulatedOrderBook] = {}
        self.leverage_limits = {}
        self.contract_specs: Dict[str, dict] = {}
        self.equity = INITIAL_EQUITY
        self.used_margin = 0.0

        self.positions: Dict[Tuple[str, str], dict] = {}
        self.pending_orders: List[dict] = []
        self.order_id_counter = 1000
        self.total_realized_pnl = 0.0
        self.latency_simulation = True
        self.engine = None
        self._feature_cache: Dict[str, dict] = {}
        self.db = Database() if use_db else None
        self.client = BitGetClient(BITGET_API_KEY, BITGET_SECRET_KEY, BITGET_PASSPHRASE)

        self.ohlcv: Dict[str, Dict[str, List[dict]]] = {}
        self.trade_history: Dict[str, List[dict]] = {}
        self.confluence_history: Dict[str, Dict[str, List[float]]] = {}
        self.last_candle_ts: Dict[str, Dict[str, float]] = {}
        self.last_price: Dict[str, float] = {}
        self._btc_confluence_cache = {}
        self._last_confluence_update = 0
        self.discovered_assets: List[str] = []
        self.asset_correlations: Dict[str, Dict[str, float]] = {}

    async def warm_up(self, preloaded_data=None):
        if preloaded_data:
            log.info("Warming up with preloaded data...")
            self.discovered_assets = preloaded_data["discovered_assets"]
            self.contract_specs = preloaded_data["contract_specs"]
            self.leverage_limits = preloaded_data["leverage_limits"]
            self.ohlcv = preloaded_data["ohlcv"]
            self.confluence_history = preloaded_data["confluence_history"]
            self.last_candle_ts = preloaded_data["last_candle_ts"]
            self.last_price = preloaded_data["last_price"]

            for sym in self.discovered_assets + [BTC_SYMBOL]:
                price = self.last_price.get(sym, 1.0)
                self.books[sym] = SimulatedOrderBook(sym, price)
            log.info(f"Warm-up complete (preloaded {len(self.discovered_assets)} assets).")
            return

        log.info("Starting warm-up...")

        # 1. Discover Assets by Volume (with persistence)
        if self.db:
            last_ts, cached_assets = self.db.get_discovered_assets()
        else:
            last_ts, cached_assets = 0, []
        age_hours = (time.time() - last_ts) / 3600

        if cached_assets and age_hours < ASSET_REDISCOVERY_HOURS:
            log.info(f"Using cached assets from DB (age: {age_hours:.1f}h)")
            self.discovered_assets = cached_assets
            # Still need tickers for initial price baseline
            tickers = await self.client.get_tickers()
        else:
            log.info(f"Discovering top assets (cache age: {age_hours:.1f}h)...")
            tickers = await self.client.get_tickers()
            # Sort by usdtVolume descending
            sorted_tickers = sorted(tickers, key=lambda x: float(x.get("usdtVolume", 0)), reverse=True)

            discovered = []
            for t in sorted_tickers:
                sym = t["symbol"]
                # Filter: only USDT futures, not omitted, not stablecoins (proxy: ends with USDT)
                if sym.endswith("USDT") and sym not in ASSET_OMITTED:
                    # Exclude known stables if they show up in volume
                    if sym.replace("USDT", "") in ["USDC", "DAI", "BUSD", "EUR", "GBP"]:
                        continue
                    discovered.append(sym)
                    if len(discovered) >= ASSETS_COUNT:
                        break

            self.discovered_assets = discovered
            self.db.save_discovered_assets(discovered)
            log.info(f"Top {len(discovered)} assets discovered by volume.")

        # 2. Fetch contract specs for discovered assets
        specs = await self.client.get_symbols()
        spec_map = {s['symbol']: s for s in specs}

        for sym in self.discovered_assets + [BTC_SYMBOL]:
            s = spec_map.get(sym)
            if s:
                self.contract_specs[sym] = s
                self.leverage_limits[sym] = float(s.get('maxLever', 20))
                # Initialize structures
                price = float(next((t['lastPr'] for t in tickers if t['symbol'] == sym), 1.0))
                self.books[sym] = SimulatedOrderBook(sym, price)
                self.ohlcv[sym] = {tf: [] for tf in AVAILABLE_TIMEFRAMES}
                self.confluence_history[sym] = {tf: [] for tf in ["15m", "1H", "4H", "1D", "1W"]}
                self.last_candle_ts[sym] = {tf: 0 for tf in AVAILABLE_TIMEFRAMES}
                self.last_price[sym] = price

        symbols = self.discovered_assets + [BTC_SYMBOL]
        semaphore = asyncio.Semaphore(5) # Reduced to stay within strict limits

        async def fetch_symbol_data(sym):
            async with semaphore:
                # Add a small staggered delay to prevent burst 429s
                await asyncio.sleep(0.1 * random.random())
                # 1. Fetch OHLCV for all relevant timeframes
                tf_map = {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1H": 3600, "4H": 14400, "1D": 86400}

                for tf in AVAILABLE_TIMEFRAMES:
                    # [TA-005] SESSION CONTINUITY: Fetch more data for session extremes
                    required_limit = 1000 if tf == "1m" else (500 if tf == ACTIVE_TIMEFRAME else 100)
                    lookback_sec = required_limit * tf_map.get(tf, 60)
                    start_ts = time.time() - lookback_sec
                    end_ts = time.time()

                    # [TECH-001] Use range-based gap detection
                    gaps = []
                    if self.db:
                        gaps = self.db.get_data_gaps(sym, tf, start_ts, end_ts)
                    else:
                        gaps = [(start_ts, end_ts)]

                    if not gaps:
                        # Data is complete in DB
                        log.debug(f"Using cached {tf} candles for {sym}")
                        db_candles = self.db.get_recent_candles(sym, tf, limit=required_limit)
                        for c in db_candles:
                            ts, o, h, l, cl, v = c
                            self.ohlcv[sym][tf].append({"ts": ts, "o": o, "h": h, "l": l, "c": cl, "v": v})
                            self.last_candle_ts[sym][tf] = ts
                    else:
                        # We have gaps, fetch from API
                        data = await self.client.get_candles(sym, tf, limit=required_limit)
                        if isinstance(data, list):
                            for c in reversed(data):
                                ts = float(c[0]) / 1000
                                o, h, l, cl, v = map(float, c[1:6])
                                if self.db:
                                    self.db.save_candle(sym, tf, ts, o, h, l, cl, v)
                                self.ohlcv[sym][tf].append({"ts": ts, "o": o, "h": h, "l": l, "c": cl, "v": v})
                                self.last_candle_ts[sym][tf] = ts
                        else:
                            log.warning(f"Failed to fetch {tf} candles for {sym}")

                    if tf == ACTIVE_TIMEFRAME and self.ohlcv[sym][tf]:
                        price = self.ohlcv[sym][tf][-1]['c']
                        self.books[sym].mid_price = price
                        self.last_price[sym] = price
                        self.books[sym]._regenerate()

                # 2. Fetch confluence history (closes only)
                for tf in ["15m", "1H", "4H", "1D", "1W"]:
                    c_data = await self.client.get_candles(sym, tf, limit=100)
                    if isinstance(c_data, list):
                        for c in reversed(c_data):
                            ts = float(c[0]) / 1000
                            cl = float(c[4])
                            self.confluence_history[sym][tf].append(cl)
                            self.last_candle_ts[sym][tf] = ts
                    else:
                        log.warning(f"Failed to fetch {tf} candles for {sym}")

        await asyncio.gather(*(fetch_symbol_data(s) for s in symbols))

        # Calculate Asset Correlations for Statistical Arbitrage Filter
        log.info("Calculating asset correlations...")
        for s1 in self.discovered_assets:
            self.asset_correlations[s1] = {}
            h1 = self.confluence_history.get(s1, {}).get("1H", [])
            if len(h1) < 20: continue
            for s2 in self.discovered_assets:
                if s1 == s2: continue
                h2 = self.confluence_history.get(s2, {}).get("1H", [])
                if len(h2) < 20: continue

                # Simple Pearson Correlation
                n = min(len(h1), len(h2))
                x, y = h1[-n:], h2[-n:]
                mu_x, mu_y = sum(x)/n, sum(y)/n
                num = sum((xi - mu_x) * (yi - mu_y) for xi, yi in zip(x, y))
                den = math.sqrt(sum((xi - mu_x)**2 for xi in x) * sum((yi - mu_y)**2 for yi in y))
                self.asset_correlations[s1][s2] = num / den if den != 0 else 0.0

        log.info("Warm-up complete.")

    async def recalculate_correlations(self):
        """[OP-008] Updates asset correlations using the most recent data."""
        log.info("Recalculating asset correlations...")
        symbols = self.discovered_assets
        for s1 in symbols:
            self.asset_correlations[s1] = {}
            h1 = self.confluence_history.get(s1, {}).get("1H", [])
            if len(h1) < 20: continue
            for s2 in symbols:
                if s1 == s2: continue
                h2 = self.confluence_history.get(s2, {}).get("1H", [])
                if len(h2) < 20: continue

                n = min(len(h1), len(h2))
                x, y = h1[-n:], h2[-n:]
                mu_x, mu_y = sum(x)/n, sum(y)/n
                num = sum((xi - mu_x) * (yi - mu_y) for xi, yi in zip(x, y))
                den = math.sqrt(sum((xi - mu_x)**2 for xi in x) * sum((yi - mu_y)**2 for yi in y))
                self.asset_correlations[s1][s2] = num / den if den != 0 else 0.0

    def get_features(self, symbol: str) -> Dict[str, float]:
        book = self.books.get(symbol)
        if not book: return {}

        # Trade Delta (Real-time, not cached)
        trades = self.trade_history.get(symbol, [])
        trade_delta = compute_trade_delta(trades[-50:]) # Last 50 trades

        # Imbalance Delta [OP-001]
        if not hasattr(self, '_imb_history'): self._imb_history = {}
        if symbol not in self._imb_history: self._imb_history[symbol] = []
        if not hasattr(self, '_mid_history'): self._mid_history = {}
        if symbol not in self._mid_history: self._mid_history[symbol] = []

        bid_vol, ask_vol = book.top_bid_ask_qty()
        total_vol = bid_vol + ask_vol
        current_imb = (bid_vol - ask_vol) / total_vol if total_vol > 0 else 0.0
        imb_delta = compute_imbalance_delta(current_imb, self._imb_history[symbol])
        self._imb_history[symbol].append(current_imb)
        if len(self._imb_history[symbol]) > 20: self._imb_history[symbol].pop(0)

        mid = (book.best_bid + book.best_ask) / 2
        mid_slope = 0
        if len(self._mid_history[symbol]) >= 5:
            mid_slope = (mid - self._mid_history[symbol][-5]) / 5
        self._mid_history[symbol].append(mid)
        if len(self._mid_history[symbol]) > 10: self._mid_history[symbol].pop(0)

        # 1. Check Cache (Only truly stable patterns that don't depend on live price)
        h_active = self.ohlcv.get(symbol, {}).get(ACTIVE_TIMEFRAME, [])
        if h_active:
            last_ts = h_active[-1]['ts']
            if symbol in self._feature_cache and self._feature_cache[symbol].get('_ts') == last_ts:
                # [PERF] If price hasn't moved significantly, return the fully cached featureset.
                # In backtests, mid is constant per candle, so this allows O(1) feature retrieval.
                if abs(mid - self._feature_cache[symbol].get('mid', 0)) < 1e-9:
                    return self._feature_cache[symbol]

                # Use cached stable features
                features = self._feature_cache[symbol].copy()

                # RE-CALCULATE PRICE-DEPENDENT FEATURES (These change every tick) [TA-002 Fix]
                # 1. Real-time metrics
                bid_vol, ask_vol = book.top_bid_ask_qty()
                total_vol = bid_vol + ask_vol
                features.update({
                    "imbalance": current_imb,
                    "imb_delta": imb_delta,
                    "mid_slope": mid_slope,
                    "spread_pct": (book.best_ask - book.best_bid) / mid if mid > 0 else 0,
                    "mid": mid,
                    "vol_pct": min(1.0, total_vol / 4000.0),
                    "trade_delta": trade_delta
                })

                # 2. Price-dependent patterns (Must re-check against live price)
                struct_data = identify_structure(h_active)
                sweep_data = detect_sweeps(h_active)
                idm_data = detect_idm(h_active)

                # Extract stable components for POI coordinate re-run
                fvg_data = {k: v for k, v in features.items() if k.startswith('fvg_') or k.startswith('nearest_fvg')}
                liq_data = {k: v for k, v in features.items() if k.endswith('_level') or k.startswith('range_')}
                sess_data = {k: v for k, v in features.items() if k.endswith('_h') or k.endswith('_l') or k.endswith('_o')}
                ob_data = {k: v for k, v in features.items() if k.startswith('ob_') or k.startswith('breaker_') or k == 'has_breaker'}

                poi_data = identify_pois(h_active, ob_data, fvg_data, liq_data, sess_data)

                features.update({
                    **struct_data,
                    **sweep_data,
                    **idm_data,
                    **poi_data
                })
                return features

        bid_vol, ask_vol = book.top_bid_ask_qty()
        total_vol = bid_vol + ask_vol
        imbalance = (bid_vol - ask_vol) / total_vol if total_vol > 0 else 0.0
        mid = (book.best_bid + book.best_ask) / 2
        spread = book.best_ask - book.best_bid
        vol_pct = min(1.0, total_vol / 4000.0)

        def get_ohlc(tf):
            h = self.ohlcv.get(symbol, {}).get(tf, [])
            if not h: return [], [], []
            relevant = h[-(INDICATOR_PRICE_HISTORY + 50):]
            return [x["c"] for x in relevant], [x["h"] for x in relevant], [x["l"] for x in relevant]

        # RSI (1m)
        c1, h1, l1 = get_ohlc("1m")
        rsi = compute_rsi(c1, timeframe="1m") if len(c1) > 25 else 50.0

        # MACD (1m)
        macd, macd_signal, macd_hist = compute_macd(c1) if len(c1) > 30 else (0,0,0)

        # ATR (1m)
        atr = compute_atr(h1, l1, c1, timeframe="1m") if len(c1) > 25 else 0.0
        vol_regime = detect_vol_regime(h1, l1, c1, atr_ind.PERIOD) if len(c1) > 30 else 'Stable'
        vol_forecast = get_volatility_forecast(h1, l1, c1) if len(c1) > 51 else 'Neutral'

        # ADX (Trend Strength) [OP-004]
        adx = compute_adx(h1, l1, c1) if len(c1) > 30 else 0.0

        # Volume Profile POC [OP-003]
        poc = identify_poc(h_active) if h_active else 0.0

        # Supertrend (1m)
        supertrend_val, supertrend_dir = compute_supertrend(h1, l1, c1, st_ind.PERIOD, st_ind.MULTIPLIER) if len(c1) > 20 else (0, 0)

        # DRT SLOW (15m)
        cs, _, _ = get_ohlc("15m")
        drt_slow = compute_drt(cs, drt_pat.PERIOD) if len(cs) >= 20 else 0.5

        # DRT FAST (5m)
        cf, _, _ = get_ohlc("5m")
        drt_fast = compute_drt(cf, drt_pat.PERIOD) if len(cf) >= 20 else 0.5

        # Legacy DRT for backwards compatibility in logs
        drt = compute_drt(c1, 20) if len(c1) >= 20 else 0.5

        # --- Pattern Recognition (Modular TA Suite) ---
        h_active = self.ohlcv.get(symbol, {}).get(ACTIVE_TIMEFRAME, [])
        h_fvg = self.ohlcv.get(symbol, {}).get(fvg_pat.TIMEFRAME, [])
        h_15m = self.ohlcv.get(symbol, {}).get("15m", [])
        h_1D = self.ohlcv.get(symbol, {}).get("1D", [])

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

        # Coordinate POIs
        poi_data = identify_pois(h_active, ob_data, fvg_data, liq_data, sess_data) if h_active else {}

        # BTC confluence cache (global per tick)
        # [T-001] ENFORCE CLOSED CANDLES to eliminate look-ahead bias
        now = time.time()
        if now - self._last_confluence_update > 0.1: # Update cache every 100ms
            self._btc_confluence_cache = {}
            for tf in ["15m", "1H", "4H", "1D"]:
                h = self.confluence_history.get(BTC_SYMBOL, {}).get(tf, [])
                # We always use the last CLOSED candle for bias to ensure stability
                if len(h) >= 3:
                    # Change in the last FULLY CLOSED candle
                    self._btc_confluence_cache[f"btc_{tf}"] = (h[-2] / h[-3] - 1)
                else:
                    self._btc_confluence_cache[f"btc_{tf}"] = 0.0
            self._last_confluence_update = now

        asset_changes = {}
        for tf in ["15m", "1H", "4H", "1D"]:
            h = self.confluence_history.get(symbol, {}).get(tf, [])
            if len(h) >= 3:
                # [T-001] Use last CLOSED candle for asset-specific MTF bias
                asset_changes[f"asset_{tf}"] = (h[-2] / h[-3] - 1)
            else:
                asset_changes[f"asset_{tf}"] = 0.0

        features = {
            "imbalance": imbalance,
            "imb_delta": imb_delta,
            "mid_slope": mid_slope,
            "spread_pct": spread / mid if mid > 0 else 0,
            "mid": mid,
            "vol_pct": vol_pct,
            "rsi": rsi,
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
            **self._btc_confluence_cache,
            **asset_changes,
        }

        # Save to cache
        if h_active:
            feat_to_cache = features.copy()
            feat_to_cache['_ts'] = h_active[-1]['ts']
            self._feature_cache[symbol] = feat_to_cache

        return features


    async def _ws_callback(self, msg):
        channel = msg.get("arg", {}).get("channel")
        instId = msg.get("arg", {}).get("instId")
        data = msg.get("data", [])
        if not data: return

        if channel == "books15":
            d = data[0]
            self.books[instId].bids = [(float(p), float(q)) for p, q in d.get("bids", [])]
            self.books[instId].asks = [(float(p), float(q)) for p, q in d.get("asks", [])]
            self.books[instId].mid_price = (self.books[instId].best_bid + self.books[instId].best_ask) / 2

        elif channel == "trade":
            for t in data:
                price = float(t[1]) if isinstance(t, list) else float(t.get("price", 0))
                size = float(t[2]) if isinstance(t, list) else float(t.get("size", 0))
                ts_ms = float(t[0]) if isinstance(t, list) else float(t.get("ts", 0))
                ts = ts_ms / 1000
                side = t[3] if isinstance(t, list) else t.get("side", "buy")

                self.last_price[instId] = price

                # Update trade history
                if instId not in self.trade_history: self.trade_history[instId] = []
                self.trade_history[instId].append({"price": price, "size": size, "side": side, "ts": ts})
                if len(self.trade_history[instId]) > 200: self.trade_history[instId].pop(0)

                if self.db:
                    self.db.save_tick(instId, ts, price, side, size)
                self._update_candles(instId, price, size, ts)

    def _update_candles(self, symbol, price, size, ts):
        tf_map = {
            "1m": 60, "5m": 300, "15m": 900, "30m": 1800,
            "1H": 3600, "4H": 14400, "1D": 86400
        }
        for tf_name, seconds in tf_map.items():
            if tf_name not in AVAILABLE_TIMEFRAMES: continue

            candle_start = (ts // seconds) * seconds
            last_ts = self.last_candle_ts[symbol].get(tf_name, 0)

            if candle_start > last_ts:
                # New candle
                self.ohlcv[symbol][tf_name].append({"ts": candle_start, "o": price, "h": price, "l": price, "c": price, "v": size})
                if len(self.ohlcv[symbol][tf_name]) > 1000: self.ohlcv[symbol][tf_name].pop(0)

                # Persistence for all fetched timeframes to enable future reuse
                if self.db:
                    prev = self.ohlcv[symbol][tf_name][-2] if len(self.ohlcv[symbol][tf_name]) > 1 else None
                    if prev:
                        self.db.save_candle(symbol, tf_name, prev["ts"], prev["o"], prev["h"], prev["l"], prev["c"], prev["v"])

                # Update confluence history if it's a tracking timeframe
                if tf_name in self.confluence_history[symbol]:
                    self.confluence_history[symbol][tf_name].append(price)
                    if len(self.confluence_history[symbol][tf_name]) > 200: self.confluence_history[symbol][tf_name].pop(0)

                self.last_candle_ts[symbol][tf_name] = candle_start
            else:
                # Update current candle
                if self.ohlcv[symbol][tf_name]:
                    curr = self.ohlcv[symbol][tf_name][-1]
                    curr["h"] = max(curr["h"], price)
                    curr["l"] = min(curr["l"], price)
                    curr["c"] = price
                    curr["v"] += size

                    if tf_name in self.confluence_history[symbol]:
                        self.confluence_history[symbol][tf_name][-1] = price

    async def _external_feed_loop(self, queue):
        log.info("Starting external feed loop")
        while True:
            try:
                # This queue will be a multiprocessing.Queue passed from compare.py
                msg = await asyncio.to_thread(queue.get)
                if msg is None:
                    log.info("External feed received stop signal.")
                    if self.engine:
                        self.engine.stop_event.set()
                    break
                await self._ws_callback(msg)
            except Exception as e:
                log.error(f"External feed error: {e}")

    async def data_feed_task(self, engine, external_feed=None):
        symbols = self.discovered_assets + [BTC_SYMBOL]
        if external_feed is None:
            ws_client = BitGetWSClient(symbols, self._ws_callback)
            asyncio.create_task(ws_client.run())
        else:
            asyncio.create_task(self._external_feed_loop(external_feed))

        last_heartbeat = time.time()
        while True:
            for sym in symbols:
                book = self.books[sym]
                # Check for activity before updating
                if engine.books[sym].bids != book.bids or engine.books[sym].asks != book.asks:
                    engine.books[sym].bids = list(book.bids)
                    engine.books[sym].asks = list(book.asks)
                    engine.books[sym].timestamp = time.time()

            await self._process_orders()
            engine.equity = self.equity

            # Heartbeat log
            now = time.time()
            if now - last_heartbeat > 60:
                log.debug("Simulator data_feed heartbeat")
                last_heartbeat = now

            await asyncio.sleep(0.1)

    async def _process_orders(self):
        fills = []
        now = time.time()
        for o in list(self.pending_orders):
            sym = o["symbol"]
            side = o["pos_side"]
            price = self.last_price.get(sym)
            if not price: continue

            # Breakeven Trigger Logic
            if USE_BREAKEVEN_TRIGGER and o["type"] == "stop":
                pos = self.positions.get((sym, side))
                if pos and not o.get("is_breakeven"):
                    entry = pos["entry_price"]
                    max_lev = self.leverage_limits.get(sym, 20)

                    # Calculate current ROE
                    if side == "buy":
                        roe = (price / entry - 1) * max_lev
                    else:
                        roe = (entry / price - 1) * max_lev

                    if roe >= BREAKEVEN_ROI_THRESHOLD:
                        # Move SL to Entry + Fees + Profit Buffer
                        # Calculate required move to cover entry fee + exit maker fee + profit buffer
                        entry_fee_rate = pos.get("entry_fee", 0) / (pos["qty"] * pos["entry_price"])
                        exit_fee_rate = MAKER_FEE

                        # total_buffer_pct is the price move needed to cover fees and desired profit ROE
                        total_buffer_roe = (entry_fee_rate + exit_fee_rate) * max_lev + BREAKEVEN_PROFIT_BUFFER
                        total_buffer_pct = total_buffer_roe / max_lev

                        if side == "buy": # Long: Move SL up
                            o["triggerPrice"] = entry * (1 + total_buffer_pct)
                        else: # Short: Move SL down
                            o["triggerPrice"] = entry * (1 - total_buffer_pct)

                        o["is_breakeven"] = True
                        log.info(f"BREAKEVEN TRIGGERED for {sym} {side.upper()} @ ROE={roe*100:.2f}% | SL moved to {o['triggerPrice']:.8f}")

            if o["type"] == "entry_limit":
                # Check if price reached our limit
                # For a BUY limit, price must be <= limit
                # For a SELL limit, price must be >= limit
                if side == "buy" and price <= o["price"]: fills.append((o, "entry"))
                elif side == "sell" and price >= o["price"]: fills.append((o, "entry"))

                # Chase/Timeout logic
                elif now - o.get("ts", now) > LIMIT_CHASE_TIMEOUT:
                    # In a real bot, we'd reposition. For simulation, let's just "take" it
                    # to keep the data flowing, or expire it. Let's convert to market-ish fill.

                    # Re-verify margin at current price before filling timeout
                    fill_price = self.last_price.get(o["symbol"])
                    max_lev = self.leverage_limits.get(o["symbol"], 20)
                    new_margin = (o["qty"] * fill_price) / max_lev
                    estimated_fee = o["qty"] * fill_price * TAKER_FEE

                    # available_balance already accounts for the 'reserved_margin' (o["reserved_margin"])
                    # so we check if the new required total fits.
                    current_avail = self.equity - (self.used_margin - o.get("reserved_margin", 0))
                    if current_avail < (new_margin + estimated_fee):
                        log.warning(f"CANCELLED TIMEOUT ENTRY {o['symbol']} {o['pos_side'].upper()}: Insufficient margin at new price {fill_price:.8f}")
                        if o in self.pending_orders:
                            self.used_margin -= o.get("reserved_margin", 0)
                            self.pending_orders.remove(o)
                        if self.engine:
                            pos_key = f"{o['symbol']}_{o['pos_side']}"
                            if pos_key in self.engine.pending_entries:
                                self.engine.pending_entries.remove(pos_key)
                        continue

                    fills.append((o, "entry_timeout"))

            elif o["type"] == "stop":
                # Soft Stop Logic
                if SL_ORDER_TYPE == "limit":
                    # Check if price reached our limit (for BUY stop, price <= limit)
                    if side == "buy" and price <= o["triggerPrice"]: fills.append((o, "stop"))
                    elif side == "sell" and price >= o["triggerPrice"]: fills.append((o, "stop"))

                    # Disaster Backup: If price moves TOO FAR past our limit, market fill
                    else:
                        # Side is 'buy' (Long position): Exit if price CRASHES below our limit
                        # Side is 'sell' (Short position): Exit if price MOONS above our limit
                        if side == "buy": # Long
                            distance = (o["triggerPrice"] / price - 1)
                        else: # Short
                            distance = (price / o["triggerPrice"] - 1)

                        # Only fire if distance is positive (price bypassed limit) AND exceeds buffer
                        if distance > SL_DISASTER_BUFFER:
                            fills.append((o, "stop_disaster"))
                else:
                    # Market Stop
                    if side == "buy" and price <= o["triggerPrice"]: fills.append((o, "stop"))
                    elif side == "sell" and price >= o["triggerPrice"]: fills.append((o, "stop"))
            elif o["type"] == "tp":
                if side == "buy" and price >= o["price"]: fills.append((o, "tp"))
                elif side == "sell" and price <= o["price"]: fills.append((o, "tp"))

        for o, et in fills:
            # Simulate realistic network latency and engine processing time
            if self.latency_simulation:
                latency = random.lognormvariate(math.log(0.035), 0.4)
                await asyncio.sleep(max(0.01, min(0.3, latency)))

            if et in ["entry", "entry_timeout"]:
                # Release reserved margin from the pending limit order
                if "reserved_margin" in o:
                    self.used_margin -= o["reserved_margin"]
                    self.used_margin = max(0, self.used_margin)

                # Maker fill if et == "entry", else Taker
                order_type = "limit" if et == "entry" else "market"
                # If timeout, we might get a worse price. For simplicity, use current market.
                fill_price = o["price"] if et == "entry" else self.last_price.get(o["symbol"])

                # SLIPPAGE PROTECTION FOR TIMEOUTS
                if et == "entry_timeout" and RESTRICT_SLIPPAGE:
                    entry_price = o["price"]
                    side = o["pos_side"]
                    slippage = (fill_price / entry_price - 1) if side == "buy" else (entry_price / fill_price - 1)
                    if slippage > MAX_ENTRY_SLIPPAGE:
                        log.warning(f"CANCELLED TIMEOUT ENTRY {o['symbol']} {side.upper()}: High slippage {slippage*100:.3f}% > {MAX_ENTRY_SLIPPAGE*100}%")
                        if o in self.pending_orders: self.pending_orders.remove(o)
                        if self.engine:
                            pos_key = f"{o['symbol']}_{side}"
                            if pos_key in self.engine.pending_entries:
                                self.engine.pending_entries.remove(pos_key)
                        continue

                self._execute_entry_direct(o["symbol"], o["pos_side"], o["qty"], fill_price, o.get("btc_conf", ""), o.get("drt", 0.5), order_type, o.get("original_side"), o.get("is_contrarian", False), features=o.get("features"), strategy_id=o.get("strategy_id"))

                # Once entry is filled, add TP/SL
                sid = self.order_id_counter; self.order_id_counter += 1
                tp_orders = []
                # Check if we should use TP1+TP2 (either from config or signal presence)
                use_tp_split = (EXIT_STRATEGY == "BE+TP1+TP2" or o.get("tp1_price") is not None)

                if use_tp_split and o.get("tp1_price"):
                    tid1 = self.order_id_counter; self.order_id_counter += 1
                    tid2 = self.order_id_counter; self.order_id_counter += 1
                    tp2_price = o.get("tp2_price") or o.get("exit_price") or o.get("tp_price")
                    tp2_qty = o.get("tp2_qty") or (o["qty"] - o.get("tp1_qty", 0))

                    tp_orders.extend([
                        {"id": tid1, "symbol": o["symbol"], "pos_side": o["pos_side"], "type": "tp", "price": o["tp1_price"], "qty": o["tp1_qty"], "is_tp1": True, "original_side": o.get("original_side"), "is_contrarian": o.get("is_contrarian", False)},
                        {"id": tid2, "symbol": o["symbol"], "pos_side": o["pos_side"], "type": "tp", "price": tp2_price, "qty": tp2_qty, "is_tp2": True, "original_side": o.get("original_side"), "is_contrarian": o.get("is_contrarian", False)},
                    ])
                else:
                    tid = self.order_id_counter; self.order_id_counter += 1
                    tp_orders.append({"id": tid, "symbol": o["symbol"], "pos_side": o["pos_side"], "type": "tp", "price": o.get("tp_price") or o.get("tp2_price"), "qty": o["qty"], "original_side": o.get("original_side"), "is_contrarian": o.get("is_contrarian", False)})

                self.pending_orders.extend([
                    {"id": sid, "symbol": o["symbol"], "pos_side": o["pos_side"], "type": "stop", "triggerPrice": o["stop_price"], "qty": o["qty"], "original_side": o.get("original_side"), "is_contrarian": o.get("is_contrarian", False)},
                ] + tp_orders)
            else:
                if et == "stop_disaster":
                    order_type = "market"
                    exit_type = "stop_backup"
                elif o.get("is_ttl"):
                    order_type = "limit"
                    exit_type = "ttl"
                else:
                    order_type = TP_ORDER_TYPE if et == "tp" else SL_ORDER_TYPE
                    exit_type = et

                exit_action = "sell" if o["pos_side"] == "buy" else "buy"

                # Use limit price if it's a limit order, else calculate slippage for market
                if order_type == "limit":
                    fill_price = o.get("price") or o.get("triggerPrice")
                else:
                    fill_price = self._calculate_fill_price(o["symbol"], exit_action, o["qty"])

                self._execute_exit(o, fill_price, exit_type, order_type)

            if o in self.pending_orders:
                # If this was TP1, we don't necessarily remove other TP orders yet.
                # However, the simulator's logic for pending_orders removal usually clears
                # all for that symbol/side on exit.
                # In BE+TP1+TP2, if TP1 hits, we keep TP2.
                if o.get("is_tp1"):
                    # TP1 hit. Keep TP2.
                    self.pending_orders.remove(o)
                else:
                    self.pending_orders.remove(o)

    def get_leverage_limits(self):
        return self.leverage_limits

    def _calculate_fill_price(self, symbol, side, qty):
        book = self.books[symbol]
        levels = book.asks if side == "buy" else book.bids
        filled_qty = 0
        total_cost = 0
        if not levels: return self.last_price.get(symbol, 0)

        # Copy levels to avoid modifying the real book during calculation
        temp_levels = list(levels)
        for price, size in temp_levels:
            take = min(qty - filled_qty, size)
            total_cost += take * price
            filled_qty += take
            if filled_qty >= qty: break

        if filled_qty < qty:
            # [C-003] Order Book Impact: Apply exponential slippage if we exceed visible liquidity
            remaining = qty - filled_qty
            last_price = temp_levels[-1][0] if temp_levels else self.last_price.get(symbol, 0)

            # 1% base slippage for the portion outside the book, plus a penalty for size
            # Size penalty scales with how much we exceeded the book
            size_penalty = 1 + (remaining / (filled_qty + 1)) * 0.05
            slippage_factor = 1.01 * size_penalty

            if side == "buy":
                total_cost += remaining * last_price * slippage_factor
            else:
                total_cost += remaining * last_price * (2 - slippage_factor)

        avg_price = total_cost / qty if qty > 0 else 0

        # Respect price precision for fill
        spec = self.contract_specs.get(symbol, {})
        price_place = int(spec.get('pricePlace', 2))
        return round(avg_price, price_place)

    def place_trade_oco(self, symbol, side, qty, entry_price, stop_price, tp_price, btc_conf="", drt=0.5, original_side=None, is_contrarian=False, features=None, **kwargs):
        """
        [TECH-001] Enhanced OCO placement with dynamic minimum notional enforcement.
        """
        spec = self.contract_specs.get(symbol, {})

        # Bitget V2 API provides minTradeUSDT. Fallback to 1.0 if missing,
        # but prioritize the exchange's actual reported minimum.
        min_usdt = float(spec.get('minTradeUSDT', 1.0))

        if RESTRICT_MIN_VAL and qty * entry_price < min_usdt:
            # [TECH-001] Log rejected trade due to notional limits (helpful for small accounts)
            log.debug(f"REJECTED {symbol} {side.upper()}: Notional {qty * entry_price:.2f} < Min {min_usdt:.2f}")
            return {"code": "3", "msg": f"order value below min {min_usdt}"}

        max_lev = self.leverage_limits.get(symbol, 20)
        required_margin = (qty * entry_price) / max_lev

        # Estimate entry fee to ensure equity can cover it immediately upon fill
        estimated_fee = qty * entry_price * (MAKER_FEE if ENTRY_ORDER_TYPE == "limit" else TAKER_FEE)

        available_balance = self.equity - self.used_margin
        if available_balance < (required_margin + estimated_fee):
            rej_msg = f"REJECTED {symbol} {side.upper()}: Insufficient margin (Required: {required_margin:.2f}, Avail: {available_balance:.2f}, Equity: {self.equity:.2f}, Used: {self.used_margin:.2f})"
            if LOG_REJECTIONS:
                log.warning(rej_msg)
            else:
                log.debug(rej_msg)
            return {"code": "1", "msg": "insufficient balance"}

        if ENTRY_ORDER_TYPE == "market":
            fill_price = self._calculate_fill_price(symbol, side, qty)

            # SLIPPAGE CONTROL
            slippage = (fill_price / entry_price - 1) if side == "buy" else (entry_price / fill_price - 1)
            if RESTRICT_SLIPPAGE and slippage > MAX_ENTRY_SLIPPAGE:
                rej_msg = f"REJECTED {symbol} {side.upper()}: High slippage {slippage*100:.3f}% > {MAX_ENTRY_SLIPPAGE*100}%"
                if LOG_REJECTIONS:
                    log.warning(rej_msg)
                else:
                    log.debug(rej_msg) # Log as debug so it goes to DB but not console
                return {"code": "2", "msg": "high slippage"}

            self._execute_entry_direct(symbol, side, qty, fill_price, btc_conf, drt, "market", original_side, is_contrarian, features=features, strategy_id=kwargs.get("strategy_id"))

            sid = self.order_id_counter; self.order_id_counter += 1
            tp_orders = []
            use_tp_split = (EXIT_STRATEGY == "BE+TP1+TP2" or kwargs.get("tp1_price") is not None)

            if use_tp_split and kwargs.get("tp1_price"):
                tid1 = self.order_id_counter; self.order_id_counter += 1
                tid2 = self.order_id_counter; self.order_id_counter += 1
                tp2_price = kwargs.get("tp2_price") or tp_price or kwargs.get("exit_price")
                tp2_qty = kwargs.get("tp2_qty") or (qty - kwargs.get("tp1_qty", 0))

                tp_orders.extend([
                    {"id": tid1, "symbol": symbol, "pos_side": side, "type": "tp", "price": kwargs["tp1_price"], "qty": kwargs["tp1_qty"], "is_tp1": True, "original_side": original_side, "is_contrarian": is_contrarian},
                    {"id": tid2, "symbol": symbol, "pos_side": side, "type": "tp", "price": tp2_price, "qty": tp2_qty, "is_tp2": True, "original_side": original_side, "is_contrarian": is_contr},
                ])
            else:
                tid = self.order_id_counter; self.order_id_counter += 1
                tp_orders.append({"id": tid, "symbol": symbol, "pos_side": side, "type": "tp", "price": tp_price, "qty": qty, "original_side": original_side, "is_contrarian": is_contrarian})

            self.pending_orders.extend([
                {"id": sid, "symbol": symbol, "pos_side": side, "type": "stop", "triggerPrice": stop_price, "qty": qty, "original_side": original_side, "is_contrarian": is_contrarian},
            ] + tp_orders)
            return {"code": "00000", "data": {"orderId": str(sid)}}
        else:
            # Limit Entry
            eid = self.order_id_counter; self.order_id_counter += 1
            self.used_margin += required_margin
            order_data = {
                "id": eid, "symbol": symbol, "pos_side": side, "type": "entry_limit",
                "price": entry_price, "qty": qty, "ts": time.time(),
                "stop_price": stop_price, "tp_price": tp_price,
                "btc_conf": btc_conf, "drt": drt,
                "original_side": original_side, "is_contrarian": is_contrarian,
                "reserved_margin": required_margin,
                "features": features
            }
            order_data.update(kwargs)
            self.pending_orders.append(order_data)
            side_str = side.upper()
            if is_contrarian:
                side_str = f"{original_side.upper()} [Flipped to {side.upper()}]"
            log.info(f"PLACED LIMIT ENTRY {symbol} {side_str} {qty:.3f} @ {entry_price:.8f} | Margin Reserved: {required_margin:.2f}")
            return {"code": "00000", "data": {"orderId": str(eid)}}

    def _execute_entry_direct(self, symbol, side, qty, fill_price, btc_conf="", drt=0.5, order_type="market", original_side=None, is_contrarian=False, features=None, strategy_id=None):
        now = time.time()
        fee = calculate_fees(qty, fill_price, is_maker=(order_type == "limit"))
        self.equity -= fee

        max_lev = self.leverage_limits.get(symbol, 20)
        margin = (qty * fill_price) / max_lev
        self.used_margin += margin

        pos_key = (symbol, side)
        if pos_key in self.positions:
            # Scale up existing position
            existing = self.positions[pos_key]
            total_qty = existing["qty"] + qty
            # Weighted average entry price
            avg_price = (existing["entry_price"] * existing["qty"] + fill_price * qty) / total_qty

            existing.update({
                "qty": total_qty,
                "entry_price": avg_price,
                "entry_fee": existing["entry_fee"] + fee,
                "margin": existing["margin"] + margin
            })
            log.info(f"SCALED POSITION {symbol} {side.upper()}: qty={total_qty:.3f} avg_price={avg_price:.8f}")
        else:
            self.positions[pos_key] = {
                "side": side, "qty": qty, "entry_price": fill_price, "entry_fee": fee, "btc_conf": btc_conf, "margin": margin, "entry_drt": drt,
                "original_side": original_side, "is_contrarian": is_contrarian, "ts": now,
                "features": features
            }
        side_str = side.upper()
        if is_contrarian:
            side_str = f"{(original_side or side).upper()} [Flipped to {side.upper()}]"

        log.info(f"FILLED ENTRY {symbol} {side_str} [Strat: {strategy_id}] {qty:.3f} @ {fill_price:.8f} ({order_type.upper()}) [{btc_conf}] drt={drt:.4f} | equity={self.equity:.2f} used_margin={self.used_margin:.2f}")

        if self.engine:
            self.engine._report_entry(symbol, side, qty, fill_price, original_side, is_contrarian, ts=now, strategy_id=strategy_id, features=features)

    def _execute_exit(self, order, fill_price, exit_type, order_type="market"):
        sym = order["symbol"]
        side = order["pos_side"]
        is_be = order.get("is_breakeven", False)
        is_tp1 = order.get("is_tp1", False)
        pos = self.positions.get((sym, side))
        if not pos: return

        # Fetch real-time DRT for exit audit
        exit_features = self.get_features(sym)
        exit_drt = exit_features.get("drt", 0.5)

        qty = min(order["qty"], pos["qty"])
        is_partial = qty < pos["qty"]

        pnl = calculate_pnl(qty, pos["entry_price"], fill_price, side)

        fee = calculate_fees(qty, fill_price, is_maker=(order_type == "limit"))

        # entry_fee proportional to qty exited
        proportional_entry_fee = pos["entry_fee"] * (qty / (pos["qty"] if not pos.get("initial_qty") else pos["initial_qty"]))

        round_trip_pnl = pnl - fee - proportional_entry_fee
        self.equity += (pnl - fee)

        # Partial margin release
        margin_release = pos.get("margin", 0) * (qty / pos["qty"])
        self.used_margin -= margin_release
        self.used_margin = max(0, self.used_margin)
        pos["margin"] -= margin_release

        side_str = side.upper()
        if pos.get("is_contrarian"):
            side_str = f"{pos.get('original_side', side).upper()} [Flipped to {side.upper()}]"

        log.info(f"EXIT {'PARTIAL' if is_partial else 'FULL'} {sym} {side_str} [Strat: {pos.get('strategy_id')}] {exit_type.upper()} ({order_type.upper()}) @ {fill_price:.8f} PnL={pnl:.4f} net={round_trip_pnl:.4f} "
                 f"[{pos['btc_conf']}] drt_entry={pos.get('entry_drt',0.5):.4f} drt_exit={exit_drt:.4f} | "
                 f"equity={self.equity:.2f} used_margin={self.used_margin:.2f}")

        if is_partial:
            # Update position
            if not pos.get("initial_qty"): pos["initial_qty"] = pos["qty"]
            pos["qty"] -= qty

            # If TP1 hit, move Stop Loss to halfway between Entry and TP1 (Aggressive BE)
            if is_tp1:
                # Find the existing STOP order
                for o in self.pending_orders:
                    if o["symbol"] == sym and o["pos_side"] == side and o["type"] == "stop":
                        # Update quantity to remaining
                        o["qty"] = pos["qty"]

                        # Move SL price to halfway between entry and exit (fill_price)
                        entry_price = pos["entry_price"]
                        new_sl = (entry_price + fill_price) / 2

                        # Respect precision
                        spec = self.contract_specs.get(sym, {})
                        price_place = int(spec.get('pricePlace', 2))
                        o["triggerPrice"] = round(new_sl, price_place)
                        o["is_breakeven"] = True # Mark as protected

                        log.info(f"TP1 HIT: SL for {sym} {side.upper()} moved to {o['triggerPrice']:.8f} (Halfway Entry/TP1)")
                        break
        else:
            del self.positions[(sym, side)]
            self.pending_orders = [o for o in self.pending_orders if not (o["symbol"] == sym and o["pos_side"] == side)]

        if self.engine: self.engine._report_exit(sym, side, round_trip_pnl, exit_type=exit_type, is_be=is_be, is_partial=is_partial, features=pos.get("features"), margin=margin_release)
