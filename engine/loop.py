"""
1. Summary: Specialized orchestration engine managing active asynchronously running trading routines.
2. Description: Coordinates periodic heartbeats, maintenance sweeps, portfolio equity monitors, and high-frequency strategy evaluation tick runs.
3. Context: Primary operational scheduler decoupled from local bookkeepers or risk evaluators.
"""
import asyncio
import time
import logging
from typing import Dict, List, Any, Optional

from orderbook import OrderBook
from ta.scoring import ScoringEngine

log = logging.getLogger("scalper.engine.loop")

class TradingLoop:
    def __init__(self, engine, ledger, risk, reporter, regime, sync, exchange, router, config_context):
        self.engine = engine
        self.ledger = ledger
        self.risk = risk
        self.reporter = reporter
        self.regime = regime
        self.sync = sync
        self.exchange = exchange
        self.router = router
        self.config = config_context

        self._last_mid = {}
        self._last_features = {}
        self._last_activity = {}

    async def run(self, preloaded_data=None, external_feed=None):
        self.engine.start_time = time.time()

        # Handle signals for graceful manual shutdown
        try:
            import signal, os
            loop = asyncio.get_running_loop()
            def handle_shutdown():
                if self.engine.stop_event.is_set():
                    log.critical("Force shutdown requested. Exiting immediately.")
                    os._exit(1)
                log.info("Shutdown signal received. Starting graceful exit...")
                self.engine.stop_event.set()

            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, handle_shutdown)
        except Exception as e:
            log.debug(f"Signal handlers not supported: {e}")

        if self.engine.mode == "paper":
            await self.exchange.warm_up(preloaded_data=preloaded_data)
            self.engine.enabled_assets = self.exchange.discovered_assets
        else:
            # 1. Discover assets from exchange
            tickers = await self.exchange.get_tickers()
            sorted_tickers = sorted(tickers, key=lambda x: float(x.get("usdtVolume", 0)), reverse=True)

            demo_whitelist = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XAUUSDT", "NEARUSDT"]

            # Ensure BTC is always mapped even if not in enabled_assets
            if self.engine.mode == "demo" and hasattr(self.exchange, "symbol_map"):
                for t in sorted_tickers:
                    if t['symbol'] in ["BTCUSDT", "SBTCUSDT"]:
                         self.exchange.symbol_map["BTCUSDT"] = t['symbol']
                         self.exchange.rev_symbol_map[t['symbol']] = "BTCUSDT"
                         break

            # 2. Apply Whitelist / Discovery
            if self.engine.mode == "demo":
                self.engine.enabled_assets = []
                for s in demo_whitelist:
                    for t in sorted_tickers:
                        sym = t['symbol']
                        if sym == s or sym == f"S{s}":
                            self.engine.enabled_assets.append(s)

                            if hasattr(self.exchange, "symbol_map"):
                                self.exchange.symbol_map[s] = sym
                                self.exchange.rev_symbol_map[sym] = s
                            break
            else:
                normalized = [(t["symbol"], float(t.get("usdtVolume", 0) or 0)) for t in tickers]
                from tools.asset_discovery import discover_assets as run_discovery
                self.engine.enabled_assets = run_discovery(normalized, self.config.ASSET_OMITTED, self.config.ASSETS_COUNT)

            log.info(f"Exchange Initialization: {len(self.engine.enabled_assets)} assets discovered.")

            # 3. Warm up indicators for discovered assets (Filtered list)
            await self.exchange.warm_up(assets=self.engine.enabled_assets)

        if self.engine.mode == "paper":
            self.engine.leverage_limits = self.exchange.get_leverage_limits()
        else:
            try:
                specs = await self.exchange.get_symbols()
                self.engine.leverage_limits = {s['symbol']: float(s.get('maxLever', 20)) for s in specs}

                trading_equity = await self.exchange.get_trading_equity()
                self.reporter.equity = trading_equity
                self.reporter.starting_equity = trading_equity
                self.reporter.peak_equity = trading_equity
                self.engine.equity = trading_equity # keep synced
                log.info(f"Initialized equity ({'VIRTUAL' if self.config.USE_VIRTUAL_BALANCE else 'REAL'}): {self.reporter.equity:.2f} USDT")
            except Exception as e:
                log.error(f"Failed to fetch initial exchange data: {e}")
                self.engine.leverage_limits = {sym: 20 for sym in self.engine.enabled_assets + [self.config.BTC_SYMBOL]}

        # Initialize books for discovered assets
        for sym in self.engine.enabled_assets + [self.config.BTC_SYMBOL]:
            self.engine.books[sym] = OrderBook(sym)
        log.info(f"Dynamic Initialization: {len(self.engine.enabled_assets)} assets discovered and loaded.")

        if self.engine.mode != "paper":
            await self.sync.sync_exchange_state()

        asyncio.create_task(self.exchange.data_feed_task(self.engine, external_feed=external_feed))
        asyncio.create_task(self._equity_monitor())
        asyncio.create_task(self._maintenance_loop())
        trading_task = asyncio.create_task(self._trading_loop())
        if self.config.SHOW_PERIODIC_SUMMARY:
            asyncio.create_task(self._summary_task())
        if self.config.SHOW_HEARTBEAT:
            asyncio.create_task(self._heartbeat_task())

        await self.engine.stop_event.wait()
        log.info("Shutdown signal received. Waiting for open positions to finalize...")

        await trading_task

        log.info("All positions finalized. Bot stopped.")

    async def _equity_monitor(self):
        while not self.engine.stop_event.is_set():
            try:
                self.reporter.equity = await self.exchange.get_trading_equity()
                self.engine.equity = self.reporter.equity # Keep synced
            except Exception as e:
                log.error(f"Failed to sync equity: {e}")

            # Risk limits checking delegated to RiskGate (P1-1)
            elapsed = time.time() - self.engine.start_time if self.engine.start_time else 0.0
            if self.risk.check_limits(
                equity=self.reporter.equity,
                starting_equity=self.reporter.starting_equity,
                peak_equity=self.reporter.peak_equity,
                total_trades=self.reporter.total_trades,
                elapsed_time=elapsed
            ):
                self.engine.stop_event.set()

            if self.reporter.equity > self.reporter.peak_equity:
                self.reporter.peak_equity = self.reporter.equity

            await asyncio.sleep(0.5 if self.engine.mode == "paper" else 5.0)

    async def _maintenance_loop(self):
        await asyncio.sleep(600)

        while not self.engine.stop_event.is_set():
            try:
                if getattr(self.exchange, "db", None):
                    self.exchange.db.purge_old_data()

                if hasattr(self.exchange, "recalculate_correlations"):
                    await self.exchange.recalculate_correlations()

                await asyncio.sleep(3600)
            except Exception as e:
                log.error(f"Maintenance error: {e}")
                await asyncio.sleep(60)

    async def _summary_task(self):
        while not self.engine.stop_event.is_set():
            try:
                self.engine._log_periodic_summary()
            except Exception as e:
                log.error(f"Summary task error: {e}")
            await asyncio.sleep(self.config.SUMMARY_INTERVAL_SECONDS)

    async def _heartbeat_task(self):
        while not self.engine.stop_event.is_set():
            try:
                self.engine._log_heartbeat()
            except Exception as e:
                log.error(f"Heartbeat task error: {e}")
            await asyncio.sleep(self.config.HEARTBEAT_INTERVAL_SECONDS)

    async def _trading_loop(self):
        await asyncio.sleep(5)
        log.info("Trading loop started.")

        engine_indicators_bypassed = False
        if not engine_indicators_bypassed and self.engine.strategies:
            all_bypassed = True
            for strat in self.engine.strategies:
                 if not getattr(strat, 'params', {}).get('bypass_external_filters', False):
                     all_bypassed = False
                     break
            if all_bypassed:
                engine_indicators_bypassed = True
                log.info("Engine indicators bypassed by all active strategies.")

        while not self.engine.stop_event.is_set() or self.ledger.position_count > 0 or self.ledger.pending_count > 0:
            try:
                all_features = {}
                now = time.time()
                for sym in set(self.engine.enabled_assets + [self.config.BTC_SYMBOL]):
                    try:
                        if hasattr(self.exchange, "ready_assets") and sym not in self.exchange.ready_assets:
                            continue

                        if sym not in self.regime.asset_regimes and sym != self.config.BTC_SYMBOL:
                            self.regime.classify_asset_regimes(sym, exchange=self.exchange, enabled_assets=self.engine.enabled_assets)

                        book = self.engine.books.get(sym)
                        if not book or book.best_bid <= 0 or book.best_ask <= 0:
                            continue

                        current_mid = (book.best_bid + book.best_ask) / 2
                        if book.timestamp > 0:
                            self._last_activity[sym] = book.timestamp

                        old_mid = self._last_mid.get(sym)

                        if old_mid is not None and current_mid != old_mid:
                            direction_up = current_mid > old_mid
                            prev_feat = self._last_features.get(sym)
                            if prev_feat is not None:
                                self.engine.model.train_on_tick(sym, prev_feat, direction_up)

                        self._last_mid[sym] = current_mid

                        has_pos = self.ledger.is_open(f"{sym}_buy") or self.ledger.is_open(f"{sym}_sell")
                        last_act = self._last_activity.get(sym, 0)

                        if sym == self.config.BTC_SYMBOL or has_pos or (now - last_act < 10.0):
                            if sym in self.config.ASSET_OMITTED:
                                continue

                            if sym == self.config.BTC_SYMBOL or self.ledger.position_count < self.config.MAX_CONCURRENT_POSITIONS:
                                 is_full = (self.ledger.is_open(f"{sym}_buy") or self.ledger.is_pending(f"{sym}_buy")) and \
                                           (self.ledger.is_open(f"{sym}_sell") or self.ledger.is_pending(f"{sym}_sell"))
                                 if is_full:
                                     continue

                                 if engine_indicators_bypassed and sym != self.config.BTC_SYMBOL:
                                     feat = {}
                                 else:
                                     feat = self.exchange.get_features(sym)
                                 self._last_features[sym] = feat
                                 all_features[sym] = feat
                    except Exception as e:
                        log.error(f"Feature calculation error for {sym}: {e}")

                # 2.5 Pluggable Strategy Management
                if hasattr(self.engine, "strategy") and self.engine.strategy:
                    for pos_key in self.ledger.get_open_keys():
                        pos = self.ledger.get_position(pos_key)
                        sym = pos_key.split("_")[0]
                        feat = all_features.get(sym)
                        market_data = {"symbol": sym, "book": self.engine.books.get(sym), "equity": self.reporter.equity, "features": feat}

                        management_sig = self.engine.strategy.manage_position(pos, market_data)
                        if management_sig:
                            if management_sig.get("action") == "double_size":
                                # Ensure minimum price distance for scaling to avoid over-exposure [REPAIR]
                                book = self.engine.books.get(sym)
                                current_price = None
                                if book and book.best_bid > 0 and book.best_ask > 0:
                                    current_price = (book.best_bid + book.best_ask) / 2
                                else:
                                    current_price = self.exchange.last_price.get(sym)

                                if current_price and pos.get("entry"):
                                    price_dist = abs(current_price - pos["entry"]) / pos["entry"]
                                    min_dist = getattr(self.config, "MIN_SCALING_DISTANCE_PCT", 0.005)
                                    if price_dist < min_dist:
                                        log.info(f"SCALE REJECTED: {sym} {pos['side'].upper()} price distance {price_dist*100:.3f}% < min_scaling_distance {min_dist*100:.2f}% | Current: {current_price:.8f}, Avg Entry: {pos['entry']:.8f}")
                                        continue

                                # Scale position
                                await self.exchange.scale_position(sym, pos["side"], pos["qty"])

                # 3. TTL (Time-to-Live) Exit Check
                if getattr(self.config, "USE_TTL", False):
                    unit = self.config.ACTIVE_TIMEFRAME[-1]
                    val = int(self.config.ACTIVE_TIMEFRAME[:-1])
                    multiplier_map = {'m': 60, 'H': 3600, 'D': 86400}
                    tf_seconds = val * multiplier_map.get(unit, 60)
                    ttl_limit = tf_seconds * getattr(self.config, "TTL_CANDLE_MULTIPLIER", 15)

                    if not hasattr(self, "_ttl_logged") or self._ttl_logged != self.config.ACTIVE_TIMEFRAME:
                        log.info(f"Dynamic TTL initialized: {ttl_limit}s ({getattr(self.config, 'TTL_CANDLE_MULTIPLIER', 15)} candles of {self.config.ACTIVE_TIMEFRAME})")
                        self._ttl_logged = self.config.ACTIVE_TIMEFRAME

                    for pos_key in self.ledger.get_open_keys():
                        pos = self.ledger.get_position(pos_key)
                        if time.time() - pos.get("ts", 0) > ttl_limit:
                            sym = pos_key.split("_")[0]
                            side = pos["side"]
                            if hasattr(self.exchange, "books") and not pos.get("ttl_triggered"):
                                book = self.exchange.books.get(sym)
                                if book:
                                    mid = (book.best_bid + book.best_ask) / 2
                                    log.info(f"TTL EXPIRED for {pos_key} ({time.time() - pos['ts']:.0f}s) | Triggering Limit Exit @ {mid:.8f}")
                                    self.exchange.pending_orders.append({
                                        "symbol": sym, "pos_side": side, "type": "ttl",
                                        "price": mid, "qty": pos["qty"], "is_ttl": True
                                    })
                                    pos["ttl_triggered"] = True

                # 4. Check Signal and Trade (Skip if shutting down)
                if not self.engine.stop_event.is_set() and (self.ledger.position_count + self.ledger.pending_count) < self.config.MAX_CONCURRENT_POSITIONS:
                    for sym in self.engine.enabled_assets:
                        if hasattr(self.exchange, "ready_assets") and sym not in self.exchange.ready_assets:
                            continue

                        if (self.ledger.position_count + self.ledger.pending_count) >= self.config.MAX_CONCURRENT_POSITIONS:
                            break

                        book = self.engine.books.get(sym)
                        if not book or book.best_bid <= 0: continue

                        if self.ledger.is_open(f"{sym}_buy") and self.ledger.is_open(f"{sym}_sell"):
                            continue

                        feat = all_features.get(sym)
                        market_data = {"symbol": sym, "book": book, "equity": self.reporter.equity, "features": feat}

                        active_signals = []
                        if self.engine.strategies:
                            for strat in self.engine.strategies:
                                if hasattr(strat, "is_ready") and not strat.is_ready(sym):
                                    if not hasattr(self, "_warmup_logged"): self._warmup_logged = {}
                                    now = time.time()
                                    if now - self._warmup_logged.get(f"{sym}_{strat.name}", 0) > 60:
                                        log.info(f"{sym}: {strat.get_readiness_eta(sym)}")
                                        self._warmup_logged[f"{sym}_{strat.name}"] = now
                                    continue

                                sig = strat.get_entry_signal(market_data)
                                if sig:
                                    sig["strategy_id"] = getattr(strat, "strategy_id", strat.name)
                                    active_signals.append(sig)
                        elif hasattr(self.engine, "strategy") and self.engine.strategy:
                            sig = self.engine.strategy.get_entry_signal(market_data)
                            if sig:
                                sig["strategy_id"] = getattr(self.engine.strategy, "strategy_id", self.engine.strategy.name)
                                active_signals.append(sig)
                        else:
                            sig = self.engine.model.predict(sym, book, self.reporter.equity, features=feat)
                            if sig:
                                sig["strategy_id"] = "model"
                                active_signals.append(sig)

                        for signal in active_signals:
                            side = signal["side"]
                            strategy_id = signal.get("strategy_id", "unknown")
                            pos_key = f"{sym}_{side}"

                            # P0-3: Duplicate signal block/logging
                            if self.ledger.is_open(pos_key) or self.ledger.is_pending(pos_key):
                                comp_strat = "unknown"
                                if self.ledger.is_open(pos_key):
                                    comp_strat = self.ledger.get_position(pos_key).get("strategy_id", "unknown")
                                else:
                                    comp_strat = "pending"
                                log.warning(f"DUPLICATE BLOCK | Skipped signal for {sym} {side.upper()} from strategy '{strategy_id}' because a position is already active/pending from strategy '{comp_strat}'.")
                                continue

                            if not hasattr(self, "_ready_logged"): self._ready_logged = set()
                            if sym not in self._ready_logged:
                                log.info(f"ASSET READY: {sym} has completed all historical requirements.")
                                self._ready_logged.add(sym)

                            # 1. Scoring Confluence Gating Check
                            feat_to_score = feat if feat is not None else self.exchange.get_features(sym)
                            if not feat_to_score:
                                continue

                            from ta.scoring import ScoringEngine
                            se = ScoringEngine()

                            if strategy_id == "model":
                                scoring_result = se.evaluate(feat_to_score, side=side, config_context=self.config, dynamic_weights=self.engine.model.weights)
                            else:
                                scoring_result = se.evaluate(feat_to_score, side=side, config_context=self.config)

                            # Always write to complete signals log file
                            self.engine._write_signals_log(sym, side, strategy_id, scoring_result)

                            if scoring_result["decision"] == "REJECTED":
                                log.debug(f"Strategy {strategy_id} signal rejected by ScoringEngine: {scoring_result['reason']}")
                                continue

                            # Delegated check to RiskGate (P1-1)
                            if not self.risk.is_asset_tradable(
                                symbol=sym,
                                side=side,
                                equity=self.reporter.equity,
                                open_positions=self.ledger.get_all_positions(),
                                pending_entries=set(self.ledger.get_pending_keys()),
                                leverage_limits=self.engine.leverage_limits,
                                exchange=self.exchange,
                                books=self.engine.books,
                                features=feat_to_score,
                                signal=signal,
                                get_current_time_func=self.engine.get_current_time,
                                strategies_count=len(self.engine.strategies)
                            ):
                                continue

                            qty = signal.get("qty", 0)
                            entry = signal.get("entry_price", 0)
                            stop = signal.get("stop_price", 0)
                            tp = signal.get("exit_price", signal.get("tp_price", 0))
                            btc_conf = signal.get("btc_confluence")
                            if not btc_conf and feat_to_score:
                                btc_conf = f"1D:{feat_to_score.get('btc_1D', 0):.4f} 4H:{feat_to_score.get('btc_4H', 0):.4f} 1H:{feat_to_score.get('btc_1H', 0):.4f} 15m:{feat_to_score.get('btc_15m', 0):.4f}"
                            elif not btc_conf:
                                btc_conf = ""

                            orig_side = signal.get("original_side", side)
                            is_contr = signal.get("is_contrarian", False)

                            self.ledger.add_pending(pos_key)

                            side_str = side.upper()
                            if is_contr:
                                side_str = f"{orig_side.upper()} [Flipped to {side.upper()}]"

                            exclude = ['side', 'entry_price', 'exit_price', 'stop_price', 'qty', 'confidence', 'btc_confluence', 'original_side', 'is_contrarian', 'rsi', 'drt', 'drt_f', 'drt_s', 'vol_pct', 'strategy_id', 'symbol', 'features']
                            extra_features = {k: v for k, v in signal.items() if k not in exclude and v is not None}
                            feat_msg = " ".join([f"{k}={v}" for k, v in extra_features.items()])

                            signal_msg = (f"SIGNAL: {sym} {side_str} [Strat: {signal.get('strategy_id')}] qty={qty:.3f} "
                                          f"entry={entry:.8f} exit={tp:.8f} stop={stop:.8f} "
                                          f"[{btc_conf}] drt_f={signal.get('drt_f')} drt_s={signal.get('drt_s')} rsi={signal.get('rsi',50):.1f} "
                                          f"macd={signal.get('macd',0):.4f} vol={signal.get('vol_pct',0):.2f} {feat_msg} equity={self.reporter.equity:.2f}")

                            if getattr(self.exchange, "db", None):
                                self.exchange.db.save_signal(sym, side, entry, signal)

                            if self.config.LOG_SIGNALS:
                                log.info(signal_msg)
                            else:
                                log.debug(signal_msg)

                            log.debug(f"ROUTING SIGNAL: {sym} {side.upper()} via {signal.get('strategy_id')}")

                            if feat_to_score is not None:
                                feat_to_score["asset_regime"] = self.regime.asset_regimes.get(sym, "stable")
                                for k, v in feat_to_score.items():
                                    if k not in signal:
                                        signal[k] = v

                            signal.update({
                                "symbol": sym,
                                "features": feat_to_score
                            })

                            self.engine.session_signals += 1
                            resp = await self.router.route_signal(signal)
                            if resp.get("code") == "00000":
                                if not self.config.LOG_SIGNALS:
                                    log.info(f"Entry Triggered | {signal_msg}")
                                # Write to metrics log only for signals resulting in entries
                                self.engine._write_metrics_log(sym, side, strategy_id, scoring_result)

                            if resp.get("code") != "00000":
                                self.ledger.remove_position(pos_key)
                                self.ledger.remove_pending(pos_key)

                await asyncio.sleep(0.1)
            except Exception as e:
                log.exception(f"Trading loop error: {e}")
                await asyncio.sleep(1)
