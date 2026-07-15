import asyncio, time, logging, math
from typing import Dict, Set, List
import config
from config import *
from orderbook import OrderBook
from simulator import Simulator
from models import LearningModel, DummyModel
from engine.entry import SignalRouter

log = logging.getLogger("scalper.engine")

class Engine:
    def __init__(self, use_db=True, mode=None, config_context=None):
        self.config = config_context if config_context is not None else config.ConfigContext()
        self.mode = (mode or self.config.MODE).lower().strip(' "').strip("'")

        self.books: Dict[str, OrderBook] = {}
        self.leverage_limits = {}
        self.pending_entries: Set[str] = set() # key is 'SYMBOL_buy' or 'SYMBOL_sell'
        self.equity = self.config.INITIAL_EQUITY
        self.starting_equity = self.config.INITIAL_EQUITY
        self.peak_equity = self.config.INITIAL_EQUITY

        # open_positions key is 'SYMBOL_buy' or 'SYMBOL_sell'
        self.open_positions: Dict[str, dict] = {}
        self.enabled_assets: List[str] = []
        self.strategies: List[any] = [] # [TECH-001] Multiple active strategies

        self.total_trades = 0
        self.winning_trades = 0 # Cumulative Wins (TP + BE)
        self.tp_wins = 0        # Direct TP hits
        self.be_wins = 0        # Breakeven protected wins
        self.losing_trades = 0
        self.cumulative_pnl = 0.0
        self.gross_profit = 0.0
        self.gross_loss = 0.0
        self.session_signals = 0 # [REPAIR-20260708] Track total signals emitted

        # Performance tracking
        self.asset_stats: Dict[str, Dict[str, any]] = {}
        self.strategy_stats: Dict[str, Dict[str, any]] = {} # [TECH-001] Per-strategy performance
        self.equity_history: List[dict] = [] # [TECH-001] Chronological compounding curve

        self.asset_regimes: Dict[str, str] = {} # symbol -> 'major', 'high_beta', 'stable'
        self.last_exit_time: Dict[str, float] = {}
        self.pos_pnl: Dict[str, float] = {} # Cumulative PnL per symbol_side

        self._last_mid = {}
        self._last_features = {}
        self._last_activity = {} # symbol -> timestamp

        self.stop_event = asyncio.Event()
        self.start_time = time.time()

        if self.mode == "paper":
            from engine.simulation import SimulationEngine
            self.exchange = SimulationEngine(use_db=use_db, config_context=self.config)
            self.exchange.engine = self
            self.model = LearningModel(self.exchange)
        elif self.mode == "demo":
            from engine.exchanges.bitget import BitgetExchange
            self.exchange = BitgetExchange(self.config.BITGET_API_KEY_DEMO, self.config.BITGET_SECRET_KEY_DEMO, self.config.BITGET_PASSPHRASE_DEMO, is_demo=True, config_context=self.config)
            self.exchange.engine = self
            self.model = DummyModel()
            log.info("Initialized Bitget in DEMO mode.")
        elif self.mode == "live":
            from engine.exchanges.bitget import BitgetExchange
            self.exchange = BitgetExchange(self.config.BITGET_API_KEY, self.config.BITGET_SECRET_KEY, self.config.BITGET_PASSPHRASE, is_demo=False, config_context=self.config)
            self.exchange.engine = self
            self.model = DummyModel()
            log.info("Initialized Bitget in LIVE mode.")
        else:
            raise ValueError(f"Unknown mode: {self.mode}")

        self.router = SignalRouter(mode=self.mode, exchange=self.exchange)

    async def start(self, preloaded_data=None, external_feed=None):
        self.start_time = time.time()

        # Handle signals for graceful manual shutdown
        try:
            import signal, os
            loop = asyncio.get_running_loop()
            def handle_shutdown():
                if self.stop_event.is_set():
                    log.critical("Force shutdown requested. Exiting immediately.")
                    os._exit(1)
                log.info("Shutdown signal received. Starting graceful exit...")
                self.stop_event.set()

            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, handle_shutdown)
        except Exception as e:
            log.debug(f"Signal handlers not supported: {e}")

        if self.mode == "paper":
            await self.exchange.warm_up(preloaded_data=preloaded_data)
            self.enabled_assets = self.exchange.discovered_assets
        else:
            # 1. Discover assets from exchange
            tickers = await self.exchange.get_tickers()
            sorted_tickers = sorted(tickers, key=lambda x: float(x.get("usdtVolume", 0)), reverse=True)

            demo_whitelist = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XAUUSDT", "NEARUSDT"]

            # Ensure BTC is always mapped even if not in enabled_assets
            if self.mode == "demo" and hasattr(self.exchange, "symbol_map"):
                for t in sorted_tickers:
                    if t['symbol'] in ["BTCUSDT", "SBTCUSDT"]:
                         self.exchange.symbol_map["BTCUSDT"] = t['symbol']
                         self.exchange.rev_symbol_map[t['symbol']] = "BTCUSDT"
                         break

            # 2. Apply Whitelist / Discovery
            if self.mode == "demo":
                self.enabled_assets = []
                for s in demo_whitelist:
                    for t in sorted_tickers:
                        sym = t['symbol']
                        if sym == s or sym == f"S{s}":
                            self.enabled_assets.append(s)

                            if hasattr(self.exchange, "symbol_map"):
                                self.exchange.symbol_map[s] = sym
                                self.exchange.rev_symbol_map[sym] = s
                            break
            else:
                self.enabled_assets = []
                for t in sorted_tickers:
                    sym = t["symbol"]
                    if sym.endswith("USDT") and sym not in self.config.ASSET_OMITTED:
                        if sym.replace("USDT", "") in ["USDC", "DAI", "BUSD", "EUR", "GBP"]: continue
                        self.enabled_assets.append(sym)
                        if len(self.enabled_assets) >= self.config.ASSETS_COUNT: break

            log.info(f"Exchange Initialization: {len(self.enabled_assets)} assets discovered.")

            # 3. Warm up indicators for discovered assets (Filtered list)
            await self.exchange.warm_up(assets=self.enabled_assets)

        if self.mode == "paper":
            self.leverage_limits = self.exchange.get_leverage_limits()
        else:
            try:
                specs = await self.exchange.get_symbols()
                self.leverage_limits = {s['symbol']: float(s.get('maxLever', 20)) for s in specs}

                trading_equity = await self.exchange.get_trading_equity()
                self.equity = trading_equity
                self.starting_equity = trading_equity
                self.peak_equity = trading_equity
                log.info(f"Initialized equity ({'VIRTUAL' if self.config.USE_VIRTUAL_BALANCE else 'REAL'}): {self.equity:.2f} USDT")
            except Exception as e:
                log.error(f"Failed to fetch initial exchange data: {e}")
                self.leverage_limits = {sym: 20 for sym in self.enabled_assets + [self.config.BTC_SYMBOL]}

        # Initialize books for discovered assets
        for sym in self.enabled_assets + [self.config.BTC_SYMBOL]:
            self.books[sym] = OrderBook(sym)
        log.info(f"Dynamic Initialization: {len(self.enabled_assets)} assets discovered and loaded.")

        if self.mode != "paper":
            await self._sync_exchange_state()

        asyncio.create_task(self.exchange.data_feed_task(self, external_feed=external_feed))
        asyncio.create_task(self._equity_monitor())
        asyncio.create_task(self._maintenance_loop())
        trading_task = asyncio.create_task(self._trading_loop())
        if self.config.SHOW_PERIODIC_SUMMARY:
            asyncio.create_task(self._summary_task())
        if self.config.SHOW_HEARTBEAT:
            asyncio.create_task(self._heartbeat_task())

        await self.stop_event.wait()
        log.info("Shutdown signal received. Waiting for open positions to finalize...")

        await trading_task

        log.info("All positions finalized. Bot stopped.")
        self._print_final_stats()

    async def _equity_monitor(self):
        while not self.stop_event.is_set():
            try:
                self.equity = await self.exchange.get_trading_equity()
            except Exception as e:
                log.error(f"Failed to sync equity: {e}")

            # 1. Drawdown Limit
            if self.peak_equity > 0 and self.equity <= self.config.DRAWDOWN_LIMIT * self.peak_equity:
                log.critical(f"DRAWDOWN LIMIT HIT: equity={self.equity:.2f}, peak={self.peak_equity:.2f}")
                self.stop_event.set()

            # 2. ROI Limit (+100 PnL)
            roi = (self.equity / self.starting_equity) - 1
            if roi >= self.config.TOTAL_ROI_LIMIT:
                log.critical(f"ROI TARGET REACHED: equity={self.equity:.2f}, ROI={roi*100:.1f}%")
                self.stop_event.set()

            # 3. Trade Count Limit
            if self.total_trades >= self.config.MAX_TRADES_LIMIT:
                log.critical(f"TRADE LIMIT REACHED: {self.total_trades} trades")
                self.stop_event.set()

            # 4. Duration Limit
            if self.start_time:
                elapsed = time.time() - self.start_time
                if elapsed >= self.config.MAX_DURATION:
                    log.critical(f"DURATION LIMIT REACHED: {elapsed:.0f}s")
                    self.stop_event.set()

            if self.equity > self.peak_equity:
                self.peak_equity = self.equity

            await asyncio.sleep(0.5 if self.mode == "paper" else 5.0)

    async def _maintenance_loop(self):
        await asyncio.sleep(600)

        while not self.stop_event.is_set():
            try:
                if getattr(self.exchange, "db", None):
                    self.exchange.db.purge_old_data()

                if hasattr(self.exchange, "recalculate_correlations"):
                    await self.exchange.recalculate_correlations()

                await asyncio.sleep(3600)
            except Exception as e:
                log.error(f"Maintenance error: {e}")
                await asyncio.sleep(60)

    @property
    def profit_ratio(self) -> float:
        """
        Calculates Profit Ratio (Gross Profit / Gross Loss).
        If no losses, returns float('inf') if gross_profit > 0 else 1.0.
        """
        if self.gross_loss > 0:
            return self.gross_profit / self.gross_loss
        return float('inf') if self.gross_profit > 0 else 1.0

    def get_current_time(self, symbol: str = None) -> float:
        """
        Returns current virtual time in paper simulation/backtest mode,
        otherwise real system time.
        """
        if self.mode == "paper" and symbol:
            book = self.books.get(symbol)
            if book and book.timestamp > 0:
                return book.timestamp
        return time.time()

    def _write_metrics_log(self, symbol: str, side: str, strategy_id: str, scoring_result: dict):
        from tools.logger import setup_metrics_logging
        setup_metrics_logging(self.start_time, symbol, side, strategy_id, scoring_result)

    def _report_entry(self, symbol: str, side: str, qty: float, entry: float, orig_side: str = None, is_contr: bool = False, ts: float = None, strategy_id: str = None, features: dict = None):
        pos_key = f"{symbol}_{side}"
        if orig_side is None: orig_side = side

        leverage = self.leverage_limits.get(symbol, 20)
        margin = (qty * entry) / leverage

        entry_ts = ts if ts is not None else time.time()

        if strategy_id is None:
             strat = getattr(self, "strategy", None)
             strategy_id = getattr(strat, "strategy_id", strat.name) if strat else "model"

        stop_price = None
        tp_price = None
        tp1_price = None
        tp1_qty = None
        if features:
            stop_price = features.get("stop_price") or features.get("stop")
            tp_price = features.get("exit_price") or features.get("tp_price") or features.get("tp")
            tp1_price = features.get("tp1_price")
            tp1_qty = features.get("tp1_qty")

        if pos_key in self.open_positions:
            p = self.open_positions[pos_key]
            total_qty = p["qty"] + qty
            p["entry"] = (p["entry"] * p["qty"] + entry * qty) / total_qty
            p["qty"] = total_qty
            p["margin"] += margin
            if stop_price: p["stop_price"] = stop_price
            if tp_price: p["tp_price"] = tp_price
            if tp1_price: p["tp1_price"] = tp1_price
            if tp1_qty: p["tp1_qty"] = tp1_qty
        else:
            self.open_positions[pos_key] = {
                "side": side, "qty": qty, "entry": entry,
                "orig_side": orig_side, "is_contr": is_contr,
                "margin": margin,
                "ts": entry_ts,
                "strategy_id": strategy_id,
                "stop_price": stop_price,
                "tp_price": tp_price,
                "tp1_price": tp1_price,
                "tp1_qty": tp1_qty
            }
        if pos_key in self.pending_entries:
            self.pending_entries.remove(pos_key)

        if hasattr(self.exchange, "db"):
            self.exchange.db.save_trade(strategy_id, symbol, side, entry_ts, entry, qty)

    def _report_exit(self, symbol: str, side: str, round_trip_pnl: float, exit_type: str = "unknown", is_be: bool = False, is_partial: bool = False, features: dict = None, margin: float = 0):
        pos_key = f"{symbol}_{side}"

        if not is_partial and features:
            self.model.train_on_trade(symbol, features, round_trip_pnl)

        if self.config.USE_VIRTUAL_BALANCE or self.mode == "paper":
            self.equity += round_trip_pnl

        self.cumulative_pnl += round_trip_pnl

        if round_trip_pnl > 0:
            self.gross_profit += round_trip_pnl
        else:
            self.gross_loss += abs(round_trip_pnl)

        self.equity_history.append({
            "ts": time.time(),
            "equity": self.equity,
            "pnl": round_trip_pnl,
            "symbol": symbol
        })

        if hasattr(self.exchange, "db"):
            entry_ts = 0
            entry_price = 0
            qty = 0
            strategy_id = "model"
            if pos_key in self.open_positions:
                p = self.open_positions[pos_key]
                entry_ts = p["ts"]
                entry_price = p["entry"]
                qty = p["qty"]
                strategy_id = p.get("strategy_id", "model")

            self.exchange.db.save_trade(
                strategy_id, symbol, side, entry_ts, entry_price, qty,
                exit_ts=time.time(), exit_price=self.exchange.last_price.get(symbol),
                pnl=round_trip_pnl, exit_type=exit_type
            )

        if symbol not in self.asset_stats:
            self.asset_stats[symbol] = {
                "buy_wins": 0, "buy_losses": 0, "sell_wins": 0, "sell_losses": 0,
                "pnl": 0.0, "tp_wins": 0, "be_wins": 0, "buy_pnl": 0.0, "sell_pnl": 0.0,
                "total_margin": 0.0
            }

        self.asset_stats[symbol]["total_margin"] += margin
        self.asset_stats[symbol]["pnl"] += round_trip_pnl
        if side == "buy": self.asset_stats[symbol]["buy_pnl"] += round_trip_pnl
        else: self.asset_stats[symbol]["sell_pnl"] += round_trip_pnl

        strategy_id = "model"
        if pos_key in self.open_positions:
            strategy_id = self.open_positions[pos_key].get("strategy_id", "model")

        if strategy_id not in self.strategy_stats:
            self.strategy_stats[strategy_id] = {
                "buy_wins": 0, "buy_losses": 0, "sell_wins": 0, "sell_losses": 0,
                "pnl": 0.0, "tp_wins": 0, "be_wins": 0, "total_trades": 0
            }

        self.strategy_stats[strategy_id]["pnl"] += round_trip_pnl
        self.pos_pnl[pos_key] = self.pos_pnl.get(pos_key, 0.0) + round_trip_pnl

        if is_partial:
            return

        total_trade_pnl = self.pos_pnl.pop(pos_key, 0.0)
        self.total_trades += 1
        self.strategy_stats[strategy_id]["total_trades"] += 1

        if pos_key in self.open_positions:
            del self.open_positions[pos_key]

        if pos_key in self.pending_entries:
            self.pending_entries.remove(pos_key)

        self.last_exit_time[symbol] = self.get_current_time(symbol)

        if total_trade_pnl > 0:
            self.winning_trades += 1
            if exit_type == "tp":
                self.tp_wins += 1
                self.asset_stats[symbol]["tp_wins"] += 1
                self.strategy_stats[strategy_id]["tp_wins"] += 1
            elif is_be:
                self.be_wins += 1
                self.asset_stats[symbol]["be_wins"] += 1
                self.strategy_stats[strategy_id]["be_wins"] += 1

            if side == "buy":
                self.asset_stats[symbol]["buy_wins"] += 1
                self.strategy_stats[strategy_id]["buy_wins"] += 1
            else:
                self.asset_stats[symbol]["sell_wins"] += 1
                self.strategy_stats[strategy_id]["sell_wins"] += 1
        else:
            if exit_type in ["tp", "ttl"]:
                log.warning(f"GROSS WIN / NET LOSS on {symbol} [{exit_type.upper()}]: PnL={total_trade_pnl:.4f} (fees consumed profit)")
            self.losing_trades += 1
            if side == "buy":
                self.asset_stats[symbol]["buy_losses"] += 1
                self.strategy_stats[strategy_id]["buy_losses"] += 1
            else:
                self.asset_stats[symbol]["sell_losses"] += 1
                self.strategy_stats[strategy_id]["sell_losses"] += 1

    def _print_final_stats(self):
        elapsed = time.time() - self.start_time if self.start_time else 0
        hours, rem = divmod(elapsed, 3600)
        minutes, seconds = divmod(rem, 60)
        win_rate = self.winning_trades / self.total_trades * 100 if self.total_trades > 0 else 0
        tp_win_pct = self.tp_wins / self.total_trades * 100 if self.total_trades > 0 else 0
        be_win_pct = self.be_wins / self.total_trades * 100 if self.total_trades > 0 else 0

        log.info(f"===== FINAL STATS =====")
        log.info(f"Session duration: {int(hours)}h {int(minutes)}m {int(seconds)}s")
        log.info(f"Total trades: {self.total_trades}")
        log.info(f"Total Wins: {self.winning_trades} ({win_rate:.1f}%) | TP Hits: {self.tp_wins} ({tp_win_pct:.1f}%) | BE Wins: {self.be_wins} ({be_win_pct:.1f}%)")
        log.info(f"Losses: {self.losing_trades}")
        log.info(f"Cumulative PnL: {self.cumulative_pnl:.2f} USDT")
        log.info(f"Final equity: {self.equity:.2f} USDT")
        log.info(f"Peak equity: {self.peak_equity:.2f} USDT")

        if self.strategy_stats:
            log.info(f"--- Strategy Performance ---")
            for sid, stats in self.strategy_stats.items():
                total = stats["total_trades"]
                wr = (stats["buy_wins"] + stats["sell_wins"]) / total * 100 if total > 0 else 0
                log.info(f"{sid:20} | PnL: {stats['pnl']:7.2f} | Trades: {total:4} | Win%: {wr:5.1f}% | TP/BE: {stats['tp_wins']}/{stats['be_wins']}")

        if self.equity_history:
            log.info(f"--- Chronological Compounding Curve ---")
            step = max(1, len(self.equity_history) // 20)
            for i in range(0, len(self.equity_history), step):
                entry = self.equity_history[i]
                roi = (entry["equity"] / self.starting_equity - 1) * 100
                log.info(f"Trade #{i+1:3} | {entry['symbol']:10} | PnL: {entry['pnl']:7.2f} | Equity: {entry['equity']:10.2f} | ROI: {roi:7.1f}%")

        if self.asset_stats:
            log.info(f"--- Asset Performance ---")
            sorted_assets = sorted(self.asset_stats.items(), key=lambda x: x[1]['pnl'], reverse=True)
            for sym, stats in sorted_assets:
                b_total = stats['buy_wins'] + stats['buy_losses']
                s_total = stats['sell_wins'] + stats['sell_losses']
                b_winrate = (stats['buy_wins'] / b_total * 100) if b_total > 0 else 0
                s_winrate = (stats['sell_wins'] / s_total * 100) if s_total > 0 else 0

                log.info(f"{sym:10} | PnL: {stats['pnl']:7.2f} | "
                         f"Long: {stats['buy_wins']}/{b_total} ({b_winrate:5.1f}%) | "
                         f"Short: {stats['sell_wins']}/{s_total} ({s_winrate:5.1f}%) | "
                         f"TP/BE: {stats.get('tp_wins',0)}/{stats.get('be_wins',0)}")

    def _classify_asset_regimes(self, symbol=None):
        targets = [symbol] if symbol else self.enabled_assets
        for sym in targets:
            h = self.exchange.ohlcv.get(sym, {}).get("1H", [])
            if not h:
                self.asset_regimes[sym] = 'major'
                continue

            closes = [c['c'] for c in h]
            highs = [c['h'] for c in h]
            lows = [c['l'] for c in h]
            from ta.indicators.atr import compute_atr
            atr = compute_atr(highs, lows, closes, period=20)
            price = closes[-1]
            atr_pct = (atr / price) if price > 0 else 0

            if sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
                self.asset_regimes[sym] = 'major'
            elif atr_pct > 0.005:
                self.asset_regimes[sym] = 'high_beta'
            else:
                self.asset_regimes[sym] = 'stable'

        if not symbol:
            counts = {r: list(self.asset_regimes.values()).count(r) for r in ['major', 'high_beta', 'stable']}
            log.info(f"REGIMES | Classification Complete: {counts}")

    def _asset_is_tradable(self, symbol: str, side: str, features: dict = None, signal: dict = None) -> bool:
        if signal and signal.get("bypass_global_filters"):
            return True

        if hasattr(self.exchange, "asset_correlations"):
            corrs = self.exchange.asset_correlations.get(symbol, {})
            for other_sym, score in corrs.items():
                if score > 0.9:
                    if f"{other_sym}_buy" in self.open_positions or f"{other_sym}_sell" in self.open_positions:
                         from ta.patterns.spread import detect_divergence
                         h1 = self.exchange.ohlcv.get(symbol, {}).get("1m", [])
                         h2 = self.exchange.ohlcv.get(other_sym, {}).get("1m", [])
                         div = detect_divergence(h1, h2, score)

                         if div.get('divergence_active') and div['recommended_side'] == side:
                             log.debug(f"STAT-ARB | Overriding correlation block for {symbol} {side}: Z={div['z_score']:.2f}")
                             continue

                         return False

        # Check volume
        book = self.books.get(symbol)
        if book:
            bid_vol, ask_vol = book.top_bid_ask_qty()
            if self.config.RESTRICT_LIQUIDITY and (bid_vol < 1 or ask_vol < 1):
                return False

        pos_key = f"{symbol}_{side}"
        if pos_key in self.open_positions or (pos_key in self.pending_entries and signal is None):
            return False

        if len(self.strategies) <= 1:
            other_side = "sell" if side == "buy" else "buy"
            other_key = f"{symbol}_{other_side}"
            if other_key in self.open_positions or other_key in self.pending_entries:
                return False

        last_exit = self.last_exit_time.get(symbol, 0)
        cooldown = self.config.REENTRY_COOLDOWN
        if features and features.get("atr") and features.get("mid"):
            atr_pct = features["atr"] / features["mid"]
            scale_factor = max(0.2, min(3.0, 0.001 / (atr_pct + 1e-9)))
            cooldown *= scale_factor

        current_time = self.get_current_time(symbol)
        if current_time - last_exit < cooldown:
            return False

        return True

    async def _trading_loop(self):
        await asyncio.sleep(5)
        log.info("Trading loop started.")

        engine_indicators_bypassed = False
        if not engine_indicators_bypassed and self.strategies:
            all_bypassed = True
            for strat in self.strategies:
                 if not getattr(strat, 'params', {}).get('bypass_external_filters', False):
                     all_bypassed = False
                     break
            if all_bypassed:
                engine_indicators_bypassed = True
                log.info("Engine indicators bypassed by all active strategies.")

        while not self.stop_event.is_set() or self.open_positions or self.pending_entries:
            try:
                all_features = {}
                now = time.time()
                for sym in set(self.enabled_assets + [self.config.BTC_SYMBOL]):
                    try:
                        if hasattr(self.exchange, "ready_assets") and sym not in self.exchange.ready_assets:
                            continue

                        if sym not in self.asset_regimes and sym != self.config.BTC_SYMBOL:
                            self._classify_asset_regimes(sym)

                        book = self.books.get(sym)
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
                                self.model.train_on_tick(sym, prev_feat, direction_up)

                        self._last_mid[sym] = current_mid

                        has_pos = f"{sym}_buy" in self.open_positions or f"{sym}_sell" in self.open_positions
                        last_act = self._last_activity.get(sym, 0)

                        if sym == self.config.BTC_SYMBOL or has_pos or (now - last_act < 10.0):
                            if sym in self.config.ASSET_OMITTED:
                                continue

                            if sym == self.config.BTC_SYMBOL or len(self.open_positions) < self.config.MAX_CONCURRENT_POSITIONS:
                                 is_full = (f"{sym}_buy" in self.open_positions or f"{sym}_buy" in self.pending_entries) and \
                                           (f"{sym}_sell" in self.open_positions or f"{sym}_sell" in self.pending_entries)
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
                if hasattr(self, "strategy"):
                    for pos_key in list(self.open_positions.keys()):
                        pos = self.open_positions[pos_key]
                        sym = pos_key.split("_")[0]
                        feat = all_features.get(sym)
                        market_data = {"symbol": sym, "book": self.books.get(sym), "equity": self.equity, "features": feat}

                        management_sig = self.strategy.manage_position(pos, market_data)
                        if management_sig:
                            if management_sig.get("action") == "double_size":
                                # Ensure minimum price distance for scaling to avoid over-exposure [REPAIR]
                                book = self.books.get(sym)
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

                    for pos_key in list(self.open_positions.keys()):
                        pos = self.open_positions[pos_key]
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
                if not self.stop_event.is_set() and (len(self.open_positions) + len(self.pending_entries)) < self.config.MAX_CONCURRENT_POSITIONS:
                    for sym in self.enabled_assets:
                        if hasattr(self.exchange, "ready_assets") and sym not in self.exchange.ready_assets:
                            continue

                        if (len(self.open_positions) + len(self.pending_entries)) >= self.config.MAX_CONCURRENT_POSITIONS:
                            break

                        book = self.books.get(sym)
                        if not book or book.best_bid <= 0: continue

                        if f"{sym}_buy" in self.open_positions and f"{sym}_sell" in self.open_positions:
                            continue

                        feat = all_features.get(sym)
                        market_data = {"symbol": sym, "book": book, "equity": self.equity, "features": feat}

                        active_signals = []
                        if self.strategies:
                            for strat in self.strategies:
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
                        elif hasattr(self, "strategy") and self.strategy:
                            sig = self.strategy.get_entry_signal(market_data)
                            if sig:
                                sig["strategy_id"] = getattr(self.strategy, "strategy_id", self.strategy.name)
                                active_signals.append(sig)
                        else:
                            sig = self.model.predict(sym, book, self.equity, features=feat)
                            if sig:
                                sig["strategy_id"] = "model"
                                active_signals.append(sig)

                        for signal in active_signals:
                            side = signal["side"]
                            if f"{sym}_{side}" in self.open_positions:
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
                            strategy_id = signal.get("strategy_id", "unknown")

                            if strategy_id == "model":
                                scoring_result = se.evaluate(feat_to_score, side=side, config_context=self.config, dynamic_weights=self.model.weights)
                            else:
                                scoring_result = se.evaluate(feat_to_score, side=side, config_context=self.config)
                                # Fix the Zeroed-Out Metrics Log bug: write the actual evaluated scoring_result
                                self._write_metrics_log(sym, side, strategy_id, scoring_result)

                            if scoring_result["decision"] == "REJECTED":
                                log.debug(f"Strategy {strategy_id} signal rejected by ScoringEngine: {scoring_result['reason']}")
                                continue

                            if not self._asset_is_tradable(sym, side, features=feat_to_score, signal=signal):
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

                            pos_key = f"{sym}_{side}"
                            self.pending_entries.add(pos_key)

                            side_str = side.upper()
                            if is_contr:
                                side_str = f"{orig_side.upper()} [Flipped to {side.upper()}]"

                            exclude = ['side', 'entry_price', 'exit_price', 'stop_price', 'qty', 'confidence', 'btc_confluence', 'original_side', 'is_contrarian', 'rsi', 'drt', 'drt_f', 'drt_s', 'vol_pct', 'strategy_id', 'symbol', 'features']
                            extra_features = {k: v for k, v in signal.items() if k not in exclude and v is not None}
                            feat_msg = " ".join([f"{k}={v}" for k, v in extra_features.items()])

                            signal_msg = (f"SIGNAL: {sym} {side_str} [Strat: {signal.get('strategy_id')}] qty={qty:.3f} "
                                          f"entry={entry:.8f} exit={tp:.8f} stop={stop:.8f} "
                                          f"[{btc_conf}] drt_f={signal.get('drt_f')} drt_s={signal.get('drt_s')} rsi={signal.get('rsi',50):.1f} "
                                          f"macd={signal.get('macd',0):.4f} vol={signal.get('vol_pct',0):.2f} {feat_msg} equity={self.equity:.2f}")

                            if getattr(self.exchange, "db", None):
                                self.exchange.db.save_signal(sym, side, entry, signal)

                            if self.config.LOG_SIGNALS:
                                log.info(signal_msg)
                            else:
                                log.debug(signal_msg)

                            if not self._asset_is_tradable(sym, side, features=feat_to_score, signal=signal):
                                if pos_key in self.open_positions: del self.open_positions[pos_key]
                                if pos_key in self.pending_entries: self.pending_entries.remove(pos_key)
                                continue

                            log.debug(f"ROUTING SIGNAL: {sym} {side.upper()} via {signal.get('strategy_id')}")

                            if feat_to_score is not None:
                                feat_to_score["asset_regime"] = self.asset_regimes.get(sym, "stable")
                                for k, v in feat_to_score.items():
                                    if k not in signal:
                                        signal[k] = v

                            signal.update({
                                "symbol": sym,
                                "features": feat_to_score
                            })

                            self.session_signals += 1
                            resp = await self.router.route_signal(signal)
                            if resp.get("code") == "00000" and not self.config.LOG_SIGNALS:
                                log.info(f"Entry Triggered | {signal_msg}")

                            if resp.get("code") != "00000":
                                if pos_key in self.open_positions: del self.open_positions[pos_key]
                                if pos_key in self.pending_entries: self.pending_entries.remove(pos_key)

                await asyncio.sleep(0.1)
            except Exception as e:
                log.exception(f"Trading loop error: {e}")
                await asyncio.sleep(1)

    async def _summary_task(self):
        while not self.stop_event.is_set():
            try:
                self._log_periodic_summary()
            except Exception as e:
                log.error(f"Summary task error: {e}")
            await asyncio.sleep(self.config.SUMMARY_INTERVAL_SECONDS)

    async def _heartbeat_task(self):
        while not self.stop_event.is_set():
            try:
                self._log_heartbeat()
            except Exception as e:
                log.error(f"Heartbeat task error: {e}")
            await asyncio.sleep(self.config.HEARTBEAT_INTERVAL_SECONDS)

    def _log_heartbeat(self):
        pursued = 0
        abandoned = 0
        signaled = self.session_signals

        if self.strategies:
            for sym in self.enabled_assets:
                for strat in self.strategies:
                    state_keys = [f"{sym}_setup_state", f"{sym}_ov_setup_state", f"{sym}_atr_setup_state"]
                    for sk in state_keys:
                        state = self.exchange.db.get_strategy_state(strat.strategy_id, sk)
                        if state:
                            if "WAITING" in state:
                                if sk == f"{sym}_atr_setup_state" and state == "WAITING_FOR_SWEEP":
                                    continue
                                pursued += 1
                            elif state == "ABANDONED":
                                abandoned += 1

        elapsed = time.time() - self.start_time
        hours, rem = divmod(elapsed, 3600)
        minutes, seconds = divmod(rem, 60)
        elapsed_str = f"{int(hours)}h {int(minutes)}m {int(seconds)}s"

        ready_count = 0
        total_count = len(self.enabled_assets)
        if self.strategies:
            for sym in self.enabled_assets:
                all_ready = True
                for strat in self.strategies:
                    if hasattr(strat, "is_ready") and not strat.is_ready(sym):
                        all_ready = False; break
                if all_ready: ready_count += 1
        else:
            ready_count = len([s for s in getattr(self.exchange, "ready_assets", []) if s in self.enabled_assets])

        sim_ready = len([s for s in getattr(self.exchange, "ready_assets", []) if s in self.enabled_assets])

        pr_val = self.profit_ratio
        pr_str = f"{pr_val:.2f}" if pr_val != float('inf') else "inf"
        log.info(f"HEARTBEAT | Elapsed: {elapsed_str} | Loaded: {ready_count}/{total_count} (Progress: {sim_ready}/{total_count}) | Pursued: {pursued} | Abandoned: {abandoned} | Signaled: {signaled} | PR: {pr_str}")

    async def _sync_exchange_state(self):
        log.info(f"Synchronizing state with {self.mode.upper()} exchange...")
        try:
            positions = await self.exchange.get_positions()
            current_pos_keys = set()
            for p in positions:
                sym = p['symbol']
                side = 'buy' if p.get('holdSide') in ['long', 'buy'] else 'sell'
                qty = float(p.get('total', 0))
                entry = float(p.get('averageOpenPrice', 0))

                if qty > 0:
                    pos_key = f"{sym}_{side}"
                    current_pos_keys.add(pos_key)
                    if pos_key not in self.open_positions:
                        self.open_positions[pos_key] = {
                            "side": side, "qty": qty, "entry": entry,
                            "orig_side": side, "is_contr": False,
                            "margin": (qty * entry) / float(p.get('leverage', 20)),
                            "ts": time.time(),
                            "strategy_id": "legacy_sync"
                        }
                        log.info(f"Synced Position: {pos_key} | Qty: {qty} @ {entry}")
                    else:
                        self.open_positions[pos_key].update({"qty": qty, "entry": entry})

            for pos_key in list(self.open_positions.keys()):
                if pos_key not in current_pos_keys:
                    p = self.open_positions[pos_key]
                    if p.get("strategy_id") != "legacy_sync":
                        log.info(f"Position {pos_key} gone from exchange. Reporting exit...")

                        symbol = pos_key.split("_")[0]
                        side = p["side"]
                        qty = p["qty"]
                        entry_price = p["entry"]

                        exit_price = None
                        pnl = None
                        fee = 0.0
                        exit_type = "exchange_sync"

                        try:
                            history = await self.exchange.get_history_positions(symbol=symbol, limit=10)
                            target_hold_side = 'long' if side == 'buy' else 'short'

                            matching_pos = None
                            for hp in history:
                                if hp.get("holdSide") == target_hold_side:
                                    matching_pos = hp
                                    break

                            if matching_pos:
                                log.info(f"SYNC STATE | Found matching historical closed position on {symbol} {side}: {matching_pos}")
                                exit_price = float(matching_pos.get("closePrice") or 0.0)
                                pnl = float(matching_pos.get("realizedPL") or 0.0)
                                fee = float(matching_pos.get("fee") or 0.0)
                                exit_type = "exchange_sync"
                        except Exception as e:
                            log.warning(f"SYNC STATE | Failed to fetch position history for {pos_key}: {e}")

                        if exit_price is None:
                            try:
                                fills = await self.exchange.get_fills(symbol=symbol, limit=20)
                                closing_side = "sell" if side == "buy" else "buy"

                                matching_fill = None
                                for f in fills:
                                    if f.get("side", "").lower() == closing_side:
                                        matching_fill = f
                                        break

                                if matching_fill:
                                    log.info(f"SYNC STATE | Found matching exit order fill on {symbol} {side}: {matching_fill}")
                                    exit_price = float(matching_fill.get("price") or 0.0)
                                    fee = float(matching_fill.get("fee") or 0.0)
                            except Exception as e:
                                log.warning(f"SYNC STATE | Failed to fetch fills for {pos_key}: {e}")

                        if exit_price is None or exit_price == 0.0:
                            ticker_price = self.exchange.last_price.get(symbol, entry_price)
                            tp_target = p.get("tp_price")
                            sl_target = p.get("stop_price")

                            if tp_target and sl_target:
                                dist_to_tp = abs(ticker_price - tp_target)
                                dist_to_sl = abs(ticker_price - sl_target)
                                if dist_to_tp < dist_to_sl:
                                    exit_price = tp_target
                                    exit_type = "tp"
                                else:
                                    exit_price = sl_target
                                    exit_type = "sl"
                            else:
                                exit_price = ticker_price

                        if pnl is None:
                            is_tp = False
                            if p.get("tp_price") and abs(exit_price - p["tp_price"]) < 1e-5:
                                is_tp = True

                            entry_maker = True
                            exit_maker = is_tp

                            from tools.trading_utils import calculate_net_pnl
                            pnl = calculate_net_pnl(qty, entry_price, exit_price, side, entry_maker=entry_maker, exit_maker=exit_maker)
                            log.info(f"SYNC STATE | Calculated local fallback net P&L for {pos_key}: gross_pnl={(exit_price-entry_price)*qty if side=='buy' else (entry_price-exit_price)*qty:.4f}, exit_price={exit_price:.8f}, net_pnl={pnl:.4f}")

                        self._report_exit(symbol, side, pnl, exit_type=exit_type)
                    else:
                        log.info(f"Legacy synced position {pos_key} cleared.")
                        if pos_key in self.open_positions:
                            del self.open_positions[pos_key]

            for pos_key, pos_details in list(self.open_positions.items()):
                sym = pos_key.split("_")[0]
                side = pos_details["side"]
                qty = pos_details["qty"]
                tp1_price = pos_details.get("tp1_price")
                tp1_qty = pos_details.get("tp1_qty")

                if tp1_price and tp1_qty:
                    try:
                        open_plans = await self.exchange.get_open_tpsl_orders(sym)

                        tp1_placed = False
                        for plan in open_plans:
                            if plan.get("planType") == "profit":
                                plan_trigger = float(plan.get("triggerPrice") or 0.0)
                                if abs(plan_trigger - tp1_price) < 1e-5:
                                    tp1_placed = True
                                    break

                        if not tp1_placed:
                            log.info(f"SYNC STATE | Placing missing TP1 trigger order for {pos_key}: trigger_price={tp1_price}, qty={tp1_qty}")
                            hold_side = "long" if side == "buy" else "short"
                            await self.exchange.place_tpsl_order(
                                symbol=sym,
                                plan_type="profit",
                                trigger_price=tp1_price,
                                qty=tp1_qty,
                                hold_side=hold_side
                            )
                    except Exception as tpsl_err:
                        log.error(f"SYNC STATE | Failed to reconcile TP1 trigger order for {pos_key}: {tpsl_err}")

            orders = await self.exchange.get_open_orders()
            current_order_keys = set()
            for o in orders:
                sym = o['symbol']
                side = o['side'].lower()
                pos_key = f"{sym}_{side}"
                current_order_keys.add(pos_key)
                if pos_key not in self.pending_entries:
                    self.pending_entries.add(pos_key)
                    log.info(f"Synced Pending Order: {pos_key} | OrderId: {o.get('orderId')}")

            for pk in list(self.pending_entries):
                if pk not in current_order_keys and pk not in current_pos_keys:
                    self.pending_entries.remove(pk)
                    log.info(f"Cleared Stale Pending Entry: {pk}")

        except Exception as e:
            log.exception(f"Failed to sync exchange state: {e}")

    def _log_periodic_summary(self):
        win_rate = self.winning_trades / self.total_trades * 100 if self.total_trades > 0 else 0
        tp_win_pct = self.tp_wins / self.total_trades * 100 if self.total_trades > 0 else 0
        drawdown = (1 - self.equity / self.peak_equity) * 100 if self.peak_equity > 0 else 0
        roi = (self.equity / self.starting_equity - 1) * 100
        used_margin = getattr(self.exchange, "used_margin", 0)
        log.info(f"SUMMARY | Equity: {self.equity:.2f} | ROI: {roi:.1f}% | "
                 f"Trades: {self.total_trades} | Win%: {win_rate:.1f} (TP: {tp_win_pct:.1f}%) | "
                 f"Open: {len(self.open_positions)} | Margin: {used_margin:.2f}")
