"""
1. Summary: High-fidelity paper trading simulation engine with multi-timeframe order matching.
2. Description: Mimics live contract endpoints by tracking virtual margins, calculating transaction fees, and validating OCO limit orders against ticks. Supports 3-way take-profit splits and trailing stops with zero-slippage execution.
3. Context: Relies on config.py, database.py, orderbook.py, and tools/publisher.py. Serves as the exchange interface in paper simulation.
"""
import asyncio, time, logging, math, random
from typing import Dict, List, Set, Tuple, Optional, Any
import config
from config import *
from orderbook import SimulatedOrderBook, OrderBook
import ta.indicators.rsi as rsi_ind
import ta.indicators.atr as atr_ind
import ta.indicators.macd as macd_ind
import ta.indicators.supertrend as st_ind
import ta.patterns.drt as drt_pat
import ta.patterns.fvg as fvg_pat
from tools.trading_utils import calculate_fees, calculate_pnl, calculate_position_size
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
from database import Database
from bitget_client import BitGetClient, BitGetWSClient, RateLimiter

log = logging.getLogger("scalper.simulator")

class DataAcquisitionManager:
    """
    Manages metadata discovery, historical candle downloads, database persistence,
    live candle building, and technical feature calculations across live/demo/paper modes.
    """
    def __init__(self, use_db=True, client=None, config_context=None):
        # Apply Config Context for Dependency Injection [ARCH-003]
        self.config = config_context if config_context is not None else config.ConfigContext()

        self.ohlcv: Dict[str, Dict[str, List[dict]]] = {}
        self.trade_history: Dict[str, List[dict]] = {}
        self.confluence_history: Dict[str, Dict[str, List[float]]] = {}
        self.last_candle_ts: Dict[str, Dict[str, float]] = {}
        self.last_price: Dict[str, float] = {}
        self._btc_confluence_cache = {}
        self._last_confluence_update = 0
        self.discovered_assets: List[str] = []
        self.ready_assets: Set[str] = set()
        self.asset_correlations: Dict[str, Dict[str, float]] = {}
        self.contract_specs: Dict[str, dict] = {}
        self.leverage_limits = {}
        self.books: Dict[str, Any] = {}
        self._feature_cache: Dict[str, dict] = {}
        self.db = Database() if use_db else None

        # Proactive Rate Limiting (98% safety cap)
        if client:
            self.client = client
        else:
            from engine.exchanges.bitget import BitgetExchange
            limiter = RateLimiter(rps=BitgetExchange.DEFAULT_RPS, safety_factor=0.98)
            self.client = BitGetClient(self.config.BITGET_API_KEY, self.config.BITGET_SECRET_KEY, self.config.BITGET_PASSPHRASE, rate_limiter=limiter)

    async def warm_up(self, preloaded_data=None, assets=None):
        """Warm up indicators and historical candle series."""
        if preloaded_data:
            log.info("Warming up with preloaded data...")
            self.discovered_assets = preloaded_data["discovered_assets"]
            self.ready_assets = set(self.discovered_assets)
            self.contract_specs = preloaded_data["contract_specs"]
            self.leverage_limits = preloaded_data["leverage_limits"]
            self.ohlcv = preloaded_data["ohlcv"]
            self.confluence_history = preloaded_data["confluence_history"]
            self.last_candle_ts = preloaded_data["last_candle_ts"]
            self.last_price = preloaded_data["last_price"]

            for sym in self.discovered_assets + [self.config.BTC_SYMBOL]:
                price = self.last_price.get(sym, 1.0)
                from orderbook import SimulatedOrderBook, OrderBook
                if hasattr(self, 'positions'):
                    self.books[sym] = SimulatedOrderBook(sym, price)
                else:
                    self.books[sym] = OrderBook(sym)
            log.info(f"Warm-up complete (preloaded {len(self.discovered_assets)} assets).")
            return

        # 1. Metadata Initialization (Fast)
        log.info("Initializing metadata...")
        await self.initialize_metadata(assets)

        # 2. Async Data Acquisition (Slow)
        log.info("Starting background data acquisition...")
        asyncio.create_task(self.fetch_all_data())

    async def initialize_metadata(self, assets=None):
        """Discovers assets, fetches contract specs, and initializes book/price baseline."""
        if assets:
            self.discovered_assets = assets
            tickers = await self.client.get_tickers()
        else:
            if self.db:
                last_ts, cached_assets = self.db.get_discovered_assets()
            else:
                last_ts, cached_assets = 0, []
            age_hours = (time.time() - last_ts) / 3600

            if cached_assets and age_hours < self.config.ASSET_REDISCOVERY_HOURS:
                log.info(f"Using cached assets from DB (age: {age_hours:.1f}h)")
                self.discovered_assets = cached_assets
                tickers = await self.client.get_tickers()
            else:
                log.info(f"Discovering top assets (cache age: {age_hours:.1f}h)...")
                tickers = await self.client.get_tickers()
                sorted_tickers = sorted(tickers, key=lambda x: float(x.get("usdtVolume", 0)), reverse=True)

                discovered = []
                for t in sorted_tickers:
                    sym = t["symbol"]
                    if sym.endswith("USDT") and sym not in self.config.ASSET_OMITTED:
                        if sym.replace("USDT", "") in ["USDC", "DAI", "BUSD", "EUR", "GBP"]:
                            continue
                        discovered.append(sym)
                        if len(discovered) >= self.config.ASSETS_COUNT:
                            break

                self.discovered_assets = discovered
                if self.db:
                    self.db.save_discovered_assets(discovered)
                log.info(f"Top {len(discovered)} assets discovered by volume.")

        # Load contract specs with local JSON cache to prevent network freezes [REPAIR]
        import os, json
        specs_cache_path = "docs/temp/contract_specs_cache.json"
        specs = []
        if os.path.exists(specs_cache_path):
            try:
                with open(specs_cache_path, "r") as f:
                    specs = json.load(f)
                log.info("Loaded contract specifications from local cache.")
            except Exception as cache_err:
                log.warning(f"Failed to read local contract specs cache: {cache_err}")

        if not specs:
            try:
                log.info("Fetching contract specifications from Bitget API...")
                specs = await self.client.get_symbols()
                if specs:
                    os.makedirs(os.path.dirname(specs_cache_path), exist_ok=True)
                    with open(specs_cache_path, "w") as f:
                        json.dump(specs, f)
            except Exception as api_err:
                log.error(f"Failed to fetch contract specs from API: {api_err}")
                specs = [{"symbol": asset, "pricePlace": "2", "volumePlace": "3", "minTradeUSDT": "5"} for asset in self.discovered_assets]

        spec_map = {s['symbol']: s for s in specs}

        symbols = list(set(self.discovered_assets + [self.config.BTC_SYMBOL]))
        tickers_list = locals().get('tickers', [])

        for sym in symbols:
            s = spec_map.get(sym)
            if s:
                self.contract_specs[sym] = s
                self.leverage_limits[sym] = float(s.get('maxLever', 20))
                price = float(next((t['lastPr'] for t in tickers_list if t['symbol'] == sym), 1.0))

                from orderbook import SimulatedOrderBook, OrderBook
                if hasattr(self, 'positions'):
                    self.books[sym] = SimulatedOrderBook(sym, price)
                else:
                    self.books[sym] = OrderBook(sym)

                self.ohlcv[sym] = {tf: [] for tf in self.config.AVAILABLE_TIMEFRAMES}
                self.confluence_history[sym] = {tf: [] for tf in ["15m", "1H", "4H", "1D", "1W"]}
                self.last_candle_ts[sym] = {tf: 0 for tf in self.config.AVAILABLE_TIMEFRAMES}
                self.last_price[sym] = price
        log.info(f"Metadata initialized for {len(symbols)} assets.")

    async def fetch_all_data(self):
        """Fetches historical candles for all assets and marks them ready as completed."""
        symbols = list(set(self.discovered_assets + [self.config.BTC_SYMBOL]))

        if self.config.BTC_SYMBOL in symbols:
            log.info(f"Fetching priority data for {self.config.BTC_SYMBOL}...")
            await self.fetch_symbol_data(self.config.BTC_SYMBOL)
            self.ready_assets.add(self.config.BTC_SYMBOL)
            symbols.remove(self.config.BTC_SYMBOL)

        total = len(symbols)
        done = 0
        semaphore = asyncio.Semaphore(5)

        async def worker(sym):
            nonlocal done
            async with semaphore:
                await self.fetch_symbol_data(sym)
                self.ready_assets.add(sym)
                done += 1
                if done % 10 == 0 or done == total:
                    log.info(f"Background Warm-up: {done}/{total} assets ready.")
                log.debug(f"Asset {sym} is ready for trading.")

        if symbols:
            await asyncio.gather(*(worker(s) for s in symbols), return_exceptions=True)

        await self.recalculate_correlations()
        log.info(f"Warm-up complete. {len(self.ready_assets)} assets active.")

    async def fetch_symbol_data(self, sym):
        """Fetch OHLCV and confluence history for a single symbol."""
        await asyncio.sleep(0.1 * random.random())
        tf_map = {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1H": 3600, "4H": 14400, "1D": 86400}

        dynamic_req = {}
        if self.engine and self.engine.strategies:
            for strat in self.engine.strategies:
                if hasattr(strat, "required_history"):
                    for tf, count in strat.required_history.items():
                        dynamic_req[tf] = max(dynamic_req.get(tf, 0), count)

        for tf in self.config.AVAILABLE_TIMEFRAMES:
            default_limit = 1000 if tf == "1m" else (500 if tf == self.config.ACTIVE_TIMEFRAME else 200)
            required_limit = max(default_limit, dynamic_req.get(tf, 0))

            lookback_sec = required_limit * tf_map.get(tf, 60)
            start_ts = time.time() - lookback_sec
            end_ts = time.time()

            gaps = []
            if self.db:
                gaps = self.db.get_data_gaps(sym, tf, start_ts, end_ts)
            else:
                gaps = [(start_ts, end_ts)]

            if gaps:
                log.debug(f"Filling {len(gaps)} gaps for {sym} {tf} via history API...")
                for g_start, g_end in gaps:
                    curr_end_ms = int(g_end * 1000)

                    while curr_end_ms > g_start * 1000:
                        batch_size = 200
                        data = await self.client.get_history_candles(sym, tf, end_time=curr_end_ms, limit=batch_size)
                        if not data: break

                        valid_in_gap = 0
                        for c in data:
                            ts = int(c[0]) / 1000
                            if ts < g_start: continue
                            if ts > g_end: continue
                            o, h, l, cl, v = map(float, c[1:6])
                            if self.db:
                                self.db.save_candle(sym, tf, ts, o, h, l, cl, v)
                            valid_in_gap += 1

                        if valid_in_gap == 0: break
                        curr_end_ms = int(data[-1][0]) - 1
                        await asyncio.sleep(0.1)

            if self.db:
                db_candles = self.db.get_recent_candles(sym, tf, limit=required_limit)
                if db_candles:
                    new_candles = [{"ts": ts, "o": o, "h": h, "l": l, "c": cl, "v": v}
                                   for ts, o, h, l, cl, v in db_candles]

                    existing = self.ohlcv.get(sym, {}).get(tf, [])
                    combined = {c['ts']: c for c in (existing + new_candles)}
                    sorted_candles = sorted(combined.values(), key=lambda x: x['ts'])
                    self.ohlcv[sym][tf] = sorted_candles[-1000:]
                    self.last_candle_ts[sym][tf] = self.ohlcv[sym][tf][-1]['ts']
                    log.debug(f"Memory Populated: {sym} {tf} | {len(self.ohlcv[sym][tf])} candles")

            if tf == self.config.ACTIVE_TIMEFRAME and self.ohlcv[sym][tf]:
                price = self.ohlcv[sym][tf][-1]['c']
                self.books[sym].mid_price = price
                self.last_price[sym] = price
                if hasattr(self.books[sym], "_regenerate"):
                    self.books[sym]._regenerate()

        for tf in ["15m", "1H", "4H", "1D", "1W"]:
            c_data = await self.client.get_candles(sym, tf, limit=100)
            new_confluence = []
            if isinstance(c_data, list):
                for c in reversed(c_data):
                    ts = float(c[0]) / 1000
                    cl = float(c[4])
                    new_confluence.append((ts, cl))

                self.confluence_history[sym][tf] = [cl for ts, cl in new_confluence][-100:]

                if self.db:
                    for c in reversed(c_data):
                        ts = float(c[0]) / 1000
                        o, h, l, cl, v = map(float, c[1:6])
                        self.db.save_candle(sym, tf, ts, o, h, l, cl, v)
            else:
                log.warning(f"Failed to fetch {tf} confluence for {sym}")

    async def recalculate_correlations(self):
        """Updates asset correlations using the most recent data."""
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
        """Stateless feature calculations delegated to stateless module."""
        book = self.books.get(symbol)
        if not book: return {}

        if not hasattr(self, '_imb_history'): self._imb_history = {}
        if symbol not in self._imb_history: self._imb_history[symbol] = []
        if not hasattr(self, '_mid_history'): self._mid_history = {}
        if symbol not in self._mid_history: self._mid_history[symbol] = []

        trades = self.trade_history.get(symbol, [])
        h_active = self.ohlcv.get(symbol, {}).get(self.config.ACTIVE_TIMEFRAME, [])
        mid = (book.best_bid + book.best_ask) / 2

        if h_active:
            last_ts = h_active[-1]['ts']
            if symbol in self._feature_cache and self._feature_cache[symbol].get('_ts') == last_ts:
                if abs(mid - self._feature_cache[symbol].get('mid', 0)) < 1e-9:
                    return self._feature_cache[symbol]

        now = time.time()
        if now - self._last_confluence_update > 0.1:
            self._btc_confluence_cache = {}
            for tf in ["15m", "1H", "4H", "1D"]:
                h = self.confluence_history.get(self.config.BTC_SYMBOL, {}).get(tf, [])
                if len(h) >= 3:
                    self._btc_confluence_cache[f"btc_{tf}"] = (h[-2] / h[-3] - 1)
                else:
                    self._btc_confluence_cache[f"btc_{tf}"] = 0.0
            self._last_confluence_update = now

        is_backtest = getattr(self, "is_backtest", False)
        if not is_backtest:
            # Slices out the active fluctuating unclosed candle for each timeframe to ensure closed-candle execution
            sliced_ohlcv = {tf: data[:-1] for tf, data in self.ohlcv.get(symbol, {}).items() if len(data) > 0}
        else:
            sliced_ohlcv = self.ohlcv.get(symbol, {})

        from ta.features import extract_features
        features = extract_features(
            symbol=symbol,
            ohlcv_data=sliced_ohlcv,
            book=book,
            trade_history_list=trades,
            confluence_history_data=self.confluence_history.get(symbol, {}),
            btc_confluence_cache=self._btc_confluence_cache,
            imb_history_list=self._imb_history[symbol],
            mid_history_list=self._mid_history[symbol]
        )

        if h_active and features:
            feat_to_cache = features.copy()
            feat_to_cache['_ts'] = h_active[-1]['ts']
            self._feature_cache[symbol] = feat_to_cache

        return features

    def _update_candles(self, symbol, price, size, ts):
        tf_map = {
            "1m": 60, "5m": 300, "15m": 900, "30m": 1800,
            "1H": 3600, "4H": 14400, "1D": 86400
        }
        for tf_name, seconds in tf_map.items():
            if tf_name not in self.config.AVAILABLE_TIMEFRAMES: continue

            candle_start = (ts // seconds) * seconds
            last_ts = self.last_candle_ts[symbol].get(tf_name, 0)

            if candle_start > last_ts:
                self.ohlcv[symbol][tf_name].append({"ts": candle_start, "o": price, "h": price, "l": price, "c": price, "v": size})
                if len(self.ohlcv[symbol][tf_name]) > 1000: self.ohlcv[symbol][tf_name].pop(0)

                if self.db:
                    prev = self.ohlcv[symbol][tf_name][-2] if len(self.ohlcv[symbol][tf_name]) > 1 else None
                    if prev:
                        self.db.save_candle(symbol, tf_name, prev["ts"], prev["o"], prev["h"], prev["l"], prev["c"], prev["v"])

                if tf_name in self.confluence_history[symbol]:
                    self.confluence_history[symbol][tf_name].append(price)
                    if len(self.confluence_history[symbol][tf_name]) > 200: self.confluence_history[symbol][tf_name].pop(0)

                self.last_candle_ts[symbol][tf_name] = candle_start
            else:
                if self.ohlcv[symbol][tf_name]:
                    curr = self.ohlcv[symbol][tf_name][-1]
                    curr["h"] = max(curr["h"], price)
                    curr["l"] = min(curr["l"], price)
                    curr["c"] = price
                    curr["v"] += size

                    if tf_name in self.confluence_history[symbol] and self.confluence_history[symbol][tf_name]:
                        self.confluence_history[symbol][tf_name][-1] = price

    def _ws_callback(self, msg):
        """Unified WebSocket Callback for both live and simulator data flow."""
        channel = msg.get("arg", {}).get("channel")
        instId = msg.get("arg", {}).get("instId")
        data = msg.get("data", [])
        if not data: return

        norm_sym = instId
        if hasattr(self, "_normalize_symbol"):
            norm_sym = self._normalize_symbol(instId)

        if channel == "books15":
            d = data[0]
            if norm_sym not in self.books:
                from orderbook import SimulatedOrderBook, OrderBook
                if hasattr(self, 'positions'):
                    self.books[norm_sym] = SimulatedOrderBook(norm_sym, (float(d.get("bids", [[0]])[0][0]) + float(d.get("asks", [[0]])[0][0])) / 2)
                else:
                    self.books[norm_sym] = OrderBook(norm_sym)

            self.books[norm_sym].bids = [(float(p), float(q)) for p, q in d.get("bids", [])]
            self.books[norm_sym].asks = [(float(p), float(q)) for p, q in d.get("asks", [])]
            self.books[norm_sym].mid_price = (self.books[norm_sym].best_bid + self.books[norm_sym].best_ask) / 2

            if self.engine and norm_sym in self.engine.books:
                self.engine.books[norm_sym].update(d.get("bids", []), d.get("asks", []), ts=int(d.get("ts", 0))/1000)

        elif channel == "trade":
            for t in data:
                price = float(t[1]) if isinstance(t, list) else float(t.get("price", 0))
                size = float(t[2]) if isinstance(t, list) else float(t.get("size", 0))
                ts_ms = float(t[0]) if isinstance(t, list) else float(t.get("ts", 0))
                ts = ts_ms / 1000
                side = t[3] if isinstance(t, list) else t.get("side", "buy")

                self.last_price[norm_sym] = price

                if norm_sym not in self.trade_history: self.trade_history[norm_sym] = []
                self.trade_history[norm_sym].append({"price": price, "size": size, "side": side, "ts": ts})
                if len(self.trade_history[norm_sym]) > 200: self.trade_history[norm_sym].pop(0)

                if self.db:
                    self.db.save_tick(norm_sym, ts, price, side, size)
                self._update_candles(norm_sym, price, size, ts)

    async def _wick_parity_patcher(self, engine):
        """Ensures Wick Parity between Live and Backtest."""
        await asyncio.sleep(60)

        while not engine.stop_event.is_set():
            try:
                now = time.time()
                wait_sec = 60 - (now % 60) + 5
                await asyncio.sleep(wait_sec)

                if engine.stop_event.is_set(): break

                current_min_epoch = int(time.time() // 60)

                tfs_to_patch = ["1m"]
                if current_min_epoch % 5 == 0: tfs_to_patch.append("5m")
                if current_min_epoch % 15 == 0: tfs_to_patch.append("15m")
                if current_min_epoch % 30 == 0: tfs_to_patch.append("30m")
                if current_min_epoch % 60 == 0: tfs_to_patch.append("1H")
                if current_min_epoch % 240 == 0: tfs_to_patch.append("4H")
                if current_min_epoch % 1440 == 0: tfs_to_patch.append("1D")

                tfs_to_patch = [tf for tf in tfs_to_patch if tf in self.config.AVAILABLE_TIMEFRAMES]

                assets = list(set(self.discovered_assets + [self.config.BTC_SYMBOL]))
                active_assets = [s for s in assets if s in self.ohlcv and self.ohlcv[s].get("1m")]

                if not active_assets: continue

                log.debug(f"PARITY | Starting REST patch for {len(active_assets)} assets across {tfs_to_patch}...")

                for tf in tfs_to_patch:
                    if tf != "1m" and (time.time() % 60) > 55:
                        log.warning(f"PARITY | Cycle for {tf} interrupted to prioritize next 1m boundary")
                        break

                    for sym in active_assets:
                        if engine.stop_event.is_set(): break
                        try:
                            res = await self.client.get_candles(sym, tf, limit=2)
                            if isinstance(res, list) and len(res) >= 1:
                                for c in res:
                                    ts = float(c[0]) / 1000
                                    o, h, l, cl, v = map(float, c[1:6])

                                    if sym in self.ohlcv and tf in self.ohlcv[sym]:
                                        for entry in reversed(self.ohlcv[sym][tf]):
                                            if entry["ts"] == ts:
                                                if entry["h"] != h or entry["l"] != l or entry["c"] != cl:
                                                    entry.update({"o": o, "h": h, "l": l, "c": cl, "v": v})
                                                break

                                    if self.db:
                                        self.db.save_candle(sym, tf, ts, o, h, l, cl, v)

                        except Exception as e:
                            log.error(f"PARITY | Patch error for {sym} {tf}: {e}")

                        await asyncio.sleep(0.01)

            except Exception as e:
                log.error(f"PARITY | Global patcher error: {e}")
                await asyncio.sleep(10)

class Simulator(DataAcquisitionManager):
    """
    Subclasses DataAcquisitionManager to append high-fidelity order book matching,
    soft stop-losses, trailing-stops, split take-profits, and virtual position tracking.
    """
    def __init__(self, use_db=True, client=None, config_context=None):
        DataAcquisitionManager.__init__(self, use_db=use_db, client=client, config_context=config_context)
        self.equity = self.config.INITIAL_EQUITY
        self.used_margin = 0.0
        self.positions: Dict[Tuple[str, str], dict] = {}
        self.pending_orders: List[dict] = []
        self.order_id_counter = 1000
        self.total_realized_pnl = 0.0
        self.latency_simulation = True
        self.engine = None

    async def _external_feed_loop(self, queue):
        log.info("Starting external feed loop")
        while True:
            try:
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
        symbols = list(set(self.discovered_assets + [self.config.BTC_SYMBOL]))
        self.engine = engine

        if external_feed is None:
            ws_client = BitGetWSClient(symbols, self._ws_callback)
            asyncio.create_task(ws_client.run())
        else:
            asyncio.create_task(self._external_feed_loop(external_feed))

        asyncio.create_task(self._wick_parity_patcher(engine))

        last_heartbeat = time.time()
        while True:
            await self._process_orders()
            engine.equity = self.equity

            now = time.time()
            if now - last_heartbeat > 60:
                log.debug("Simulator data_feed heartbeat")
                last_heartbeat = now

            if engine.stop_event.is_set():
                break

            await asyncio.sleep(0.1)

    async def _process_orders(self):
        fills = []
        now = time.time()
        for o in list(self.pending_orders):
            sym = o["symbol"]
            side = o["pos_side"]
            price = self.last_price.get(sym)
            if not price: continue

            if self.config.USE_BREAKEVEN_TRIGGER and o["type"] == "stop":
                pos = self.positions.get((sym, side))
                if pos and not o.get("is_breakeven"):
                    entry = pos["entry_price"]
                    max_lev = self.leverage_limits.get(sym, 20)

                    if side == "buy":
                        roe = (price / entry - 1) * max_lev
                    else:
                        roe = (entry / price - 1) * max_lev

                    if roe >= self.config.BREAKEVEN_ROI_THRESHOLD:
                        entry_fee_rate = pos.get("entry_fee", 0) / (pos["qty"] * pos["entry_price"])
                        exit_fee_rate = self.config.MAKER_FEE

                        total_buffer_roe = (entry_fee_rate + exit_fee_rate) * max_lev + self.config.BREAKEVEN_PROFIT_BUFFER
                        total_buffer_pct = total_buffer_roe / max_lev

                        if side == "buy":
                            o["triggerPrice"] = entry * (1 + total_buffer_pct)
                        else:
                            o["triggerPrice"] = entry * (1 - total_buffer_pct)

                        o["is_breakeven"] = True
                        log.info(f"BREAKEVEN TRIGGERED for {sym} {side.upper()} @ ROE={roe*100:.2f}% | SL moved to {o['triggerPrice']:.8f}")

            if o["type"] == "entry_limit":
                if side == "buy" and price <= o["price"]: fills.append((o, "entry"))
                elif side == "sell" and price >= o["price"]: fills.append((o, "entry"))

                elif now - o.get("ts", now) > self.config.LIMIT_CHASE_TIMEOUT:
                    log.info(f"TIMEOUT: Cancelling stale limit entry for {o['symbol']} {o['pos_side'].upper()}")
                    if o in self.pending_orders:
                        self.used_margin -= o.get("reserved_margin", 0)
                        self.pending_orders.remove(o)

                    if hasattr(self, "cancel_order"):
                        real_oid = o.get("orderId")
                        if real_oid:
                             asyncio.create_task(self.cancel_order(o['symbol'], real_oid))

                    if self.engine:
                        pos_key = f"{o['symbol']}_{o['pos_side']}"
                        if pos_key in self.engine.pending_entries:
                            self.engine.pending_entries.remove(pos_key)
                    continue

            elif o["type"] == "stop":
                if self.config.SL_ORDER_TYPE == "limit":
                    if side == "buy" and price <= o["triggerPrice"]: fills.append((o, "stop"))
                    elif side == "sell" and price >= o["triggerPrice"]: fills.append((o, "stop"))
                    else:
                        if side == "buy":
                            distance = (o["triggerPrice"] / price - 1)
                        else:
                            distance = (price / o["triggerPrice"] - 1)

                        if distance > self.config.SL_DISASTER_BUFFER:
                            fills.append((o, "stop_disaster"))
                else:
                    if side == "buy" and price <= o["triggerPrice"]: fills.append((o, "stop"))
                    elif side == "sell" and price >= o["triggerPrice"]: fills.append((o, "stop"))
            elif o["type"] == "tp":
                if side == "buy" and price >= o["price"]: fills.append((o, "tp"))
                elif side == "sell" and price <= o["price"]: fills.append((o, "tp"))

        for o, et in fills:
            if self.latency_simulation:
                latency = random.lognormvariate(math.log(0.035), 0.4)
                await asyncio.sleep(max(0.01, min(0.3, latency)))

            if et in ["entry", "entry_timeout"]:
                if "reserved_margin" in o:
                    self.used_margin -= o["reserved_margin"]
                    self.used_margin = max(0, self.used_margin)

                order_type = "limit" if et == "entry" else "market"
                fill_price = o["price"] if et == "entry" else self.last_price.get(o["symbol"])

                if et == "entry_timeout" and self.config.RESTRICT_SLIPPAGE:
                    entry_price = o["price"]
                    side = o["pos_side"]
                    slippage = (fill_price / entry_price - 1) if side == "buy" else (entry_price / fill_price - 1)
                    if slippage > self.config.MAX_ENTRY_SLIPPAGE:
                        log.warning(f"CANCELLED TIMEOUT ENTRY {o['symbol']} {side.upper()}: High slippage {slippage*100:.3f}% > {self.config.MAX_ENTRY_SLIPPAGE*100}%")
                        if o in self.pending_orders: self.pending_orders.remove(o)
                        if self.engine:
                            pos_key = f"{o['symbol']}_{side}"
                            if pos_key in self.engine.pending_entries:
                                self.engine.pending_entries.remove(pos_key)
                        continue

                self._execute_entry_direct(o["symbol"], o["pos_side"], o["qty"], fill_price, o.get("btc_conf", ""), o.get("drt", 0.5), order_type, o.get("original_side"), o.get("is_contrarian", False), features=o.get("features"), strategy_id=o.get("strategy_id"))

                sid = self.order_id_counter; self.order_id_counter += 1
                tp_orders = []
                use_tp3 = (o.get("tp3_price") is not None)
                use_tp_split = (self.config.EXIT_STRATEGY == "BE+TP1+TP2" or o.get("tp1_price") is not None)

                if use_tp3:
                    tid1 = self.order_id_counter; self.order_id_counter += 1
                    tid2 = self.order_id_counter; self.order_id_counter += 1
                    tid3 = self.order_id_counter; self.order_id_counter += 1
                    tp1_price = o["tp1_price"]
                    tp2_price = o["tp2_price"]
                    tp3_price = o["tp3_price"]
                    tp1_qty = o["tp1_qty"]
                    tp2_qty = o["tp2_qty"]
                    tp3_qty = o["qty"] - tp1_qty - tp2_qty

                    tp_orders.extend([
                        {"id": tid1, "symbol": o["symbol"], "pos_side": o["pos_side"], "type": "tp", "price": tp1_price, "qty": tp1_qty, "is_tp1": True, "original_side": o.get("original_side"), "is_contrarian": o.get("is_contrarian", False)},
                        {"id": tid2, "symbol": o["symbol"], "pos_side": o["pos_side"], "type": "tp", "price": tp2_price, "qty": tp2_qty, "is_tp2": True, "original_side": o.get("original_side"), "is_contrarian": o.get("is_contrarian", False)},
                        {"id": tid3, "symbol": o["symbol"], "pos_side": o["pos_side"], "type": "tp", "price": tp3_price, "qty": tp3_qty, "is_tp3": True, "original_side": o.get("original_side"), "is_contrarian": o.get("is_contrarian", False)},
                    ])
                elif use_tp_split and o.get("tp1_price"):
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
                    order_type = self.config.TP_ORDER_TYPE if et == "tp" else self.config.SL_ORDER_TYPE
                    exit_type = et

                exit_action = "sell" if o["pos_side"] == "buy" else "buy"

                if order_type == "limit":
                    fill_price = o.get("price") or o.get("triggerPrice")
                else:
                    fill_price = self._calculate_fill_price(o["symbol"], exit_action, o["qty"])

                self._execute_exit(o, fill_price, exit_type, order_type)

            if o in self.pending_orders:
                if o.get("is_tp1"):
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

        temp_levels = list(levels)
        for price, size in temp_levels:
            take = min(qty - filled_qty, size)
            total_cost += take * price
            filled_qty += take
            if filled_qty >= qty: break

        if filled_qty < qty:
            remaining = qty - filled_qty
            last_price = temp_levels[-1][0] if temp_levels else self.last_price.get(symbol, 0)

            size_penalty = 1 + (remaining / (filled_qty + 1)) * 0.05
            slippage_factor = 1.01 * size_penalty

            if side == "buy":
                total_cost += remaining * last_price * slippage_factor
            else:
                total_cost += remaining * last_price * (2 - slippage_factor)

        avg_price = total_cost / qty if qty > 0 else 0

        spec = self.contract_specs.get(symbol, {})
        price_place = int(spec.get('pricePlace', 2))
        return round(avg_price, price_place)

    def place_trade_oco(self, symbol, side, qty, entry_price, stop_price, tp_price, btc_conf="", drt=0.5, original_side=None, is_contrarian=False, features=None, **kwargs):
        spec = self.contract_specs.get(symbol, {})
        min_usdt = float(spec.get('minTradeUSDT', 1.0))

        if self.config.RESTRICT_MIN_VAL and qty * entry_price < min_usdt:
            log.debug(f"REJECTED {symbol} {side.upper()}: Notional {qty * entry_price:.2f} < Min {min_usdt:.2f}")
            return {"code": "3", "msg": f"order value below min {min_usdt}"}

        max_lev = self.leverage_limits.get(symbol, 20)
        required_margin = (qty * entry_price) / max_lev

        # Enforce "Net Profit vs. Fee" Filter to prevent narrow fee traps [REPAIR]
        entry_order_type = kwargs.get("entry_order_type") or self.config.ENTRY_ORDER_TYPE
        if tp_price and tp_price > 0:
            entry_fee_rate = self.config.MAKER_FEE if entry_order_type == "limit" else self.config.TAKER_FEE
            exit_fee_rate = self.config.MAKER_FEE if self.config.TP_ORDER_TYPE == "limit" else self.config.TAKER_FEE

            entry_fee = qty * entry_price * entry_fee_rate
            exit_fee = qty * tp_price * exit_fee_rate
            total_expected_fees = entry_fee + exit_fee

            gross_pnl_at_tp = qty * abs(tp_price - entry_price)
            projected_net_pnl = gross_pnl_at_tp - total_expected_fees

            min_profit_pct = getattr(self.config, "MIN_NET_TP_PROFIT_PCT", 0.001)
            min_required_profit = min_profit_pct * required_margin

            if projected_net_pnl < min_required_profit:
                log.info(f"REJECTED NARROW FEE TRAP: {symbol} {side.upper()} projected net profit {projected_net_pnl:.4f} is less than required threshold {min_required_profit:.4f} ({min_profit_pct*100:.2f}% of margin) | Gross TP Profit: {gross_pnl_at_tp:.4f}, Total Fees: {total_expected_fees:.4f}")
                return {"code": "4", "msg": "net tp profit below minimum required threshold"}

        estimated_fee = qty * entry_price * (self.config.MAKER_FEE if entry_order_type == "limit" else self.config.TAKER_FEE)

        available_balance = self.equity - self.used_margin
        if available_balance < (required_margin + estimated_fee):
            rej_msg = f"REJECTED {symbol} {side.upper()}: Insufficient margin (Required: {required_margin:.2f}, Avail: {available_balance:.2f}, Equity: {self.equity:.2f}, Used: {self.used_margin:.2f})"
            if self.config.LOG_REJECTIONS:
                log.warning(rej_msg)
            else:
                log.debug(rej_msg)
            return {"code": "1", "msg": "insufficient balance"}

        if entry_order_type == "market":
            fill_price = self._calculate_fill_price(symbol, side, qty)

            slippage = (fill_price / entry_price - 1) if side == "buy" else (entry_price / fill_price - 1)
            if self.config.RESTRICT_SLIPPAGE and slippage > self.config.MAX_ENTRY_SLIPPAGE:
                rej_msg = f"REJECTED {symbol} {side.upper()}: High slippage {slippage*100:.3f}% > {self.config.MAX_ENTRY_SLIPPAGE*100}%"
                if self.config.LOG_REJECTIONS:
                    log.warning(rej_msg)
                else:
                    log.debug(rej_msg)
                return {"code": "2", "msg": "high slippage"}

            self._execute_entry_direct(symbol, side, qty, fill_price, btc_conf, drt, entry_order_type, original_side, is_contrarian, features=features, strategy_id=kwargs.get("strategy_id"))

            sid = self.order_id_counter; self.order_id_counter += 1
            tp_orders = []
            use_tp3 = (kwargs.get("tp3_price") is not None)
            use_tp_split = (self.config.EXIT_STRATEGY == "BE+TP1+TP2" or kwargs.get("tp1_price") is not None)

            if use_tp3:
                tid1 = self.order_id_counter; self.order_id_counter += 1
                tid2 = self.order_id_counter; self.order_id_counter += 1
                tid3 = self.order_id_counter; self.order_id_counter += 1
                tp1_price = kwargs["tp1_price"]
                tp2_price = kwargs["tp2_price"]
                tp3_price = kwargs["tp3_price"]
                tp1_qty = kwargs["tp1_qty"]
                tp2_qty = kwargs["tp2_qty"]
                tp3_qty = qty - tp1_qty - tp2_qty

                tp_orders.extend([
                    {"id": tid1, "symbol": symbol, "pos_side": side, "type": "tp", "price": tp1_price, "qty": tp1_qty, "is_tp1": True, "original_side": original_side, "is_contrarian": is_contrarian},
                    {"id": tid2, "symbol": symbol, "pos_side": side, "type": "tp", "price": tp2_price, "qty": tp2_qty, "is_tp2": True, "original_side": original_side, "is_contrarian": is_contrarian},
                    {"id": tid3, "symbol": symbol, "pos_side": side, "type": "tp", "price": tp3_price, "qty": tp3_qty, "is_tp3": True, "original_side": original_side, "is_contrarian": is_contrarian},
                ])
            elif use_tp_split and kwargs.get("tp1_price"):
                tid1 = self.order_id_counter; self.order_id_counter += 1
                tid2 = self.order_id_counter; self.order_id_counter += 1
                tp2_price = kwargs.get("tp2_price") or tp_price or kwargs.get("exit_price")
                tp2_qty = kwargs.get("tp2_qty") or (qty - kwargs.get("tp1_qty", 0))

                tp_orders.extend([
                    {"id": tid1, "symbol": symbol, "pos_side": side, "type": "tp", "price": kwargs["tp1_price"], "qty": kwargs["tp1_qty"], "is_tp1": True, "original_side": original_side, "is_contrarian": is_contrarian},
                    {"id": tid2, "symbol": symbol, "pos_side": side, "type": "tp", "price": tp2_price, "qty": tp2_qty, "is_tp2": True, "original_side": original_side, "is_contrarian": is_contrarian},
                ])
            else:
                tid = self.order_id_counter; self.order_id_counter += 1
                tp_orders.append({"id": tid, "symbol": symbol, "pos_side": side, "type": "tp", "price": tp_price, "qty": qty, "original_side": original_side, "is_contrarian": is_contrarian})

            self.pending_orders.extend([
                {"id": sid, "symbol": symbol, "pos_side": side, "type": "stop", "triggerPrice": stop_price, "qty": qty, "original_side": original_side, "is_contrarian": is_contrarian},
            ] + tp_orders)
            return {"code": "00000", "data": {"orderId": str(sid)}}
        else:
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
            existing = self.positions[pos_key]
            total_qty = existing["qty"] + qty
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
                "features": features,
                "strategy_id": strategy_id
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

        exit_features = self.get_features(sym)
        exit_drt = exit_features.get("drt", 0.5)

        qty = min(order["qty"], pos["qty"])
        is_partial = qty < pos["qty"]

        pnl = calculate_pnl(qty, pos["entry_price"], fill_price, side)
        fee = calculate_fees(qty, fill_price, is_maker=(order_type == "limit"))

        proportional_entry_fee = pos["entry_fee"] * (qty / (pos["qty"] if not pos.get("initial_qty") else pos["initial_qty"]))
        round_trip_pnl = pnl - fee - proportional_entry_fee
        self.equity += (pnl - fee)

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
            if not pos.get("initial_qty"): pos["initial_qty"] = pos["qty"]
            pos["qty"] -= qty

            if is_tp1:
                for o in self.pending_orders:
                    if o["symbol"] == sym and o["pos_side"] == side and o["type"] == "stop":
                        o["qty"] = pos["qty"]

                        entry_price = pos["entry_price"]
                        new_sl = (entry_price + fill_price) / 2

                        spec = self.contract_specs.get(sym, {})
                        price_place = int(spec.get('pricePlace', 2))
                        o["triggerPrice"] = round(new_sl, price_place)
                        o["is_breakeven"] = True

                        log.info(f"TP1 HIT: SL for {sym} {side.upper()} moved to {o['triggerPrice']:.8f} (Halfway Entry/TP1)")
                        break
            elif order.get("is_tp2"):
                for o in self.pending_orders:
                    if o["symbol"] == sym and o["pos_side"] == side and o["type"] == "stop":
                        o["qty"] = pos["qty"]

                        entry_price = pos["entry_price"]
                        spec = self.contract_specs.get(sym, {})
                        price_place = int(spec.get('pricePlace', 2))
                        o["triggerPrice"] = round(entry_price, price_place)
                        o["is_breakeven"] = True

                        log.info(f"TP2 HIT: SL for {sym} {side.upper()} moved to break-even {o['triggerPrice']:.8f}")
                        break
        else:
            del self.positions[(sym, side)]
            self.pending_orders = [o for o in self.pending_orders if not (o["symbol"] == sym and o["pos_side"] == side)]

        if self.engine: self.engine._report_exit(sym, side, round_trip_pnl, exit_type=exit_type, is_be=is_be, is_partial=is_partial, features=pos.get("features"), margin=margin_release)

    def _ws_callback(self, msg):
        channel = msg.get("arg", {}).get("channel")
        instId = msg.get("arg", {}).get("instId")
        data = msg.get("data", [])
        if not data: return

        if channel == "books15":
            d = data[0]
            self.books[instId].bids = [(float(p), float(q)) for p, q in d.get("bids", [])]
            self.books[instId].asks = [(float(p), float(q)) for p, q in d.get("asks", [])]
            self.books[instId].mid_price = (self.books[instId].best_bid + self.books[instId].best_ask) / 2

            if self.engine and instId in self.engine.books:
                self.engine.books[instId].update(d.get("bids", []), d.get("asks", []), ts=int(d.get("ts", 0))/1000)

        elif channel == "trade":
            for t in data:
                price = float(t[1]) if isinstance(t, list) else float(t.get("price", 0))
                size = float(t[2]) if isinstance(t, list) else float(t.get("size", 0))
                ts_ms = float(t[0]) if isinstance(t, list) else float(t.get("ts", 0))
                ts = ts_ms / 1000
                side = t[3] if isinstance(t, list) else t.get("side", "buy")

                self.last_price[instId] = price

                if instId not in self.trade_history: self.trade_history[instId] = []
                self.trade_history[instId].append({"price": price, "size": size, "side": side, "ts": ts})
                if len(self.trade_history[instId]) > 200: self.trade_history[instId].pop(0)

                if self.db:
                    self.db.save_tick(instId, ts, price, side, size)
                self._update_candles(instId, price, size, ts)
