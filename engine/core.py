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
    def __init__(self, use_db=True):
        self.books: Dict[str, OrderBook] = {}
        self.leverage_limits = {}
        self.pending_entries: Set[str] = set() # key is 'SYMBOL_buy' or 'SYMBOL_sell'
        self.equity = INITIAL_EQUITY
        self.starting_equity = INITIAL_EQUITY
        self.peak_equity = INITIAL_EQUITY

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

        if MODE == "paper":
            from engine.simulation import SimulationEngine
            self.exchange = SimulationEngine(use_db=use_db)
            self.exchange.engine = self
            self.model = LearningModel(self.exchange)
        elif MODE == "demo":
            from engine.exchanges.bitget import BitgetExchange
            self.exchange = BitgetExchange(BITGET_API_KEY_DEMO, BITGET_SECRET_KEY_DEMO, BITGET_PASSPHRASE_DEMO, is_demo=True)
            self.exchange.engine = self
            self.model = DummyModel()
            log.info("Initialized Bitget in DEMO mode.")
        elif MODE == "live":
            from engine.exchanges.bitget import BitgetExchange
            self.exchange = BitgetExchange(BITGET_API_KEY, BITGET_SECRET_KEY, BITGET_PASSPHRASE, is_demo=False)
            self.exchange.engine = self
            self.model = DummyModel()
            log.info("Initialized Bitget in LIVE mode.")
        else:
            raise ValueError(f"Unknown mode: {MODE}")

        self.router = SignalRouter(mode=MODE, exchange=self.exchange)

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

        if MODE == "paper":
            await self.exchange.warm_up(preloaded_data=preloaded_data)
            self.enabled_assets = self.exchange.discovered_assets
        else:
            # Discover assets from exchange
            tickers = await self.exchange.get_tickers()
            sorted_tickers = sorted(tickers, key=lambda x: float(x.get("usdtVolume", 0)), reverse=True)
            self.enabled_assets = []
            for t in sorted_tickers:
                sym = t["symbol"]
                if sym.endswith("USDT") and sym not in ASSET_OMITTED:
                    if sym.replace("USDT", "") in ["USDC", "DAI", "BUSD", "EUR", "GBP"]: continue
                    self.enabled_assets.append(sym)
                    if len(self.enabled_assets) >= ASSETS_COUNT: break
            log.info(f"Exchange Initialization: {len(self.enabled_assets)} assets discovered.")

        self._classify_asset_regimes()

        if MODE == "paper":
            self.leverage_limits = self.exchange.get_leverage_limits()
        else:
            # For Live/Demo, fetch leverage limits from exchange
            try:
                specs = await self.exchange.get_symbols()
                self.leverage_limits = {s['symbol']: float(s.get('maxLever', 20)) for s in specs}
            except Exception as e:
                log.error(f"Failed to fetch leverage limits: {e}")
                self.leverage_limits = {sym: 20 for sym in self.enabled_assets + [BTC_SYMBOL]}

        # Initialize books for discovered assets
        for sym in self.enabled_assets + [BTC_SYMBOL]:
            self.books[sym] = OrderBook(sym)
        log.info(f"Dynamic Initialization: {len(self.enabled_assets)} assets discovered and loaded.")

        asyncio.create_task(self.exchange.data_feed_task(self, external_feed=external_feed))
        asyncio.create_task(self._equity_monitor())
        asyncio.create_task(self._maintenance_loop())
        trading_task = asyncio.create_task(self._trading_loop())
        if SHOW_PERIODIC_SUMMARY:
            asyncio.create_task(self._summary_task())

        await self.stop_event.wait()
        log.info("Shutdown signal received. Waiting for open positions to finalize...")

        # Wait for the trading loop to return (it handles its own graceful exit)
        await trading_task

        log.info("All positions finalized. Bot stopped.")
        self._print_final_stats()

    async def _equity_monitor(self):
        while not self.stop_event.is_set():
            # Sync equity
            if MODE == "paper":
                self.equity = self.exchange.equity
            else:
                # Real balance from exchange
                # For high frequency, we might want to cache this or use WS updates
                try:
                    real_balance = await self.exchange.get_balance()
                    if real_balance is not None:
                        self.equity = real_balance
                except Exception as e:
                    log.error(f"Failed to sync real equity: {e}")

            # 1. Drawdown Limit
            if self.peak_equity > 0 and self.equity <= DRAWDOWN_LIMIT * self.peak_equity:
                log.critical(f"DRAWDOWN LIMIT HIT: equity={self.equity:.2f}, peak={self.peak_equity:.2f}")
                self.stop_event.set()

            # 2. ROI Limit (+100 PnL)
            roi = (self.equity / self.starting_equity) - 1
            if roi >= TOTAL_ROI_LIMIT:
                log.critical(f"ROI TARGET REACHED: equity={self.equity:.2f}, ROI={roi*100:.1f}%")
                self.stop_event.set()

            # 3. Trade Count Limit
            if self.total_trades >= MAX_TRADES_LIMIT:
                log.critical(f"TRADE LIMIT REACHED: {self.total_trades} trades")
                self.stop_event.set()

            # 4. Duration Limit
            if self.start_time:
                elapsed = time.time() - self.start_time
                if elapsed >= MAX_DURATION:
                    log.critical(f"DURATION LIMIT REACHED: {elapsed:.0f}s")
                    self.stop_event.set()

            if self.equity > self.peak_equity:
                self.peak_equity = self.equity

            await asyncio.sleep(0.5)

    async def _maintenance_loop(self):
        while not self.stop_event.is_set():
            try:
                if getattr(self.exchange, "db", None):
                    self.exchange.db.purge_old_data()

                # [OP-008] Periodic Correlation Refresh
                if hasattr(self.exchange, "recalculate_correlations"):
                    await self.exchange.recalculate_correlations()

                await asyncio.sleep(3600) # Every hour
            except Exception as e:
                log.error(f"Maintenance error: {e}")
                await asyncio.sleep(60)

    def _write_metrics_log(self, symbol: str, side: str, strategy_id: str, features: dict):
        """
        [TECH-001] Writes full technical module metrics to a shadow log.
        """
        import os, json
        from datetime import datetime

        log_dir = "docs/temp"
        os.makedirs(log_dir, exist_ok=True)

        # Determine filename based on start time
        start_dt = datetime.fromtimestamp(self.start_time).strftime("%Y%m%d_%H%M%S")
        filepath = os.path.join(log_dir, f"{start_dt}.metrics-log.txt")

        now = datetime.now().strftime("%H:%M:%S.%f")[:-3]

        # Flatten and sanitize features for logging
        sanitized = {}
        for k, v in features.items():
            if isinstance(v, (int, float, str, bool)) or v is None:
                sanitized[k] = v
            else:
                sanitized[k] = str(v)

        metrics_json = json.dumps(sanitized)

        with open(filepath, "a") as f:
            f.write(f"[{now}] ENTRY {symbol} {side.upper()} | Strategy: {strategy_id} | Metrics: {metrics_json}\n")

    def _report_entry(self, symbol: str, side: str, qty: float, entry: float, orig_side: str = None, is_contr: bool = False, ts: float = None, strategy_id: str = None, features: dict = None):
        pos_key = f"{symbol}_{side}"
        # If orig_side not passed (e.g. from simulator), default to current
        if orig_side is None: orig_side = side

        # Calculate Margin used for this entry
        leverage = self.leverage_limits.get(symbol, 20)
        margin = (qty * entry) / leverage

        entry_ts = ts if ts is not None else time.time()

        # [TECH-001] Determine Strategy ID for attribution
        if strategy_id is None:
             strat = getattr(self, "strategy", None)
             strategy_id = getattr(strat, "strategy_id", strat.name) if strat else "model"

        if pos_key in self.open_positions:
            # Scaling up an existing position
            p = self.open_positions[pos_key]
            total_qty = p["qty"] + qty
            # Update weighted average entry price for tracking
            p["entry"] = (p["entry"] * p["qty"] + entry * qty) / total_qty
            p["qty"] = total_qty
            p["margin"] += margin
            # Keep the ORIGINAL strategy_id as the primary owner for attribution
        else:
            self.open_positions[pos_key] = {
                "side": side, "qty": qty, "entry": entry,
                "orig_side": orig_side, "is_contr": is_contr,
                "margin": margin,
                "ts": entry_ts,
                "strategy_id": strategy_id
            }
        if pos_key in self.pending_entries:
            self.pending_entries.remove(pos_key)

        # [TECH-001] Full Module Metrics Shadow Log
        if features:
            self._write_metrics_log(symbol, side, strategy_id, features)

        # Persistence
        if hasattr(self.exchange, "db"):
            self.exchange.db.save_trade(strategy_id, symbol, side, entry_ts, entry, qty)

    def _report_exit(self, symbol: str, side: str, round_trip_pnl: float, exit_type: str = "unknown", is_be: bool = False, is_partial: bool = False, features: dict = None, margin: float = 0):
        # Local registration cleanup
        pos_key = f"{symbol}_{side}"

        # [C-004] Adaptive Learning: Feedback loop based on trade PnL
        if not is_partial and features:
            self.model.train_on_trade(symbol, features, round_trip_pnl)

        # Track session-wide metrics (always updated)
        self.cumulative_pnl += round_trip_pnl

        # [TECH-001] Record equity history for chronological compounding curve
        self.equity_history.append({
            "ts": time.time(),
            "equity": self.equity,
            "pnl": round_trip_pnl,
            "symbol": symbol
        })

        # Persistence
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

        # Accumulate margin from the position (proportional to exit)
        self.asset_stats[symbol]["total_margin"] += margin

        self.asset_stats[symbol]["pnl"] += round_trip_pnl
        if side == "buy": self.asset_stats[symbol]["buy_pnl"] += round_trip_pnl
        else: self.asset_stats[symbol]["sell_pnl"] += round_trip_pnl

        # [TECH-001] Strategy-Level Stats: Attribute PnL and trade counts to the
        # specific strategy within a Family that generated the signal.
        strategy_id = "model"
        if pos_key in self.open_positions:
            strategy_id = self.open_positions[pos_key].get("strategy_id", "model")

        if strategy_id not in self.strategy_stats:
            self.strategy_stats[strategy_id] = {
                "buy_wins": 0, "buy_losses": 0, "sell_wins": 0, "sell_losses": 0,
                "pnl": 0.0, "tp_wins": 0, "be_wins": 0, "total_trades": 0
            }

        self.strategy_stats[strategy_id]["pnl"] += round_trip_pnl

        # Track cumulative PnL for this specific trade to determine if it's a win/loss overall
        self.pos_pnl[pos_key] = self.pos_pnl.get(pos_key, 0.0) + round_trip_pnl

        if is_partial:
            return

        # Final exit processing
        total_trade_pnl = self.pos_pnl.pop(pos_key, 0.0)
        self.total_trades += 1
        self.strategy_stats[strategy_id]["total_trades"] += 1

        if pos_key in self.open_positions:
            del self.open_positions[pos_key]

        # Also ensure it's cleared from pending if it was an entry failure
        if pos_key in self.pending_entries:
            self.pending_entries.remove(pos_key)

        self.last_exit_time[symbol] = time.time()

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
        """
        [TECH-001] Enhanced final reporting with strategy breakdowns and compounding curve.
        """
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
            # Show every 10th trade or up to 20 points
            step = max(1, len(self.equity_history) // 20)
            for i in range(0, len(self.equity_history), step):
                entry = self.equity_history[i]
                roi = (entry["equity"] / self.starting_equity - 1) * 100
                log.info(f"Trade #{i+1:3} | {entry['symbol']:10} | PnL: {entry['pnl']:7.2f} | Equity: {entry['equity']:10.2f} | ROI: {roi:7.1f}%")

        if self.asset_stats:
            log.info(f"--- Asset Performance ---")
            # Sort by PnL
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

    def _classify_asset_regimes(self):
        """[OP Roadmap] Group assets into volatility buckets."""
        for sym in self.enabled_assets:
            # Classification based on 1H ATR / Price
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
            elif atr_pct > 0.005: # > 0.5% hourly move
                self.asset_regimes[sym] = 'high_beta'
            else:
                self.asset_regimes[sym] = 'stable'

        counts = {r: list(self.asset_regimes.values()).count(r) for r in ['major', 'high_beta', 'stable']}
        log.info(f"REGIMES | Classification Complete: {counts}")

    def _asset_is_tradable(self, symbol: str, side: str, features: dict = None, signal: dict = None) -> bool:
        """
        [TECH-001] Updated tradability logic to support Strategy Families.
        Families allow hedging (Long + Short) but not redundant same-side positions
        unless explicitly managed by scaling logic.

        [TECH-001] BYPASS LOGIC:
        - If 'bypass_external_filters' is True in strategy params, this Engine-level
          check (Layer 1) is skipped entirely (Correlations, Cooldowns, Regimes).
        - However, the STRATEGY itself may still require technical indicators for its
          INTERNAL logic (e.g. Sweeps need FVG/Structure), which is why the 14-day
          warm-up buffer in backtest.py may still trigger.
        """
        # [TECH-001] BYPASS OPTION (Global or per-signal)
        if getattr(config, 'BYPASS_GLOBAL_FILTERS', False):
            return True
        if signal and signal.get("bypass_global_filters"):
            return True

        # 1. Statistical Arbitrage Filter (Correlation & Mean Reversion)
        if hasattr(self.exchange, "asset_correlations"):
            corrs = self.exchange.asset_correlations.get(symbol, {})
            for other_sym, score in corrs.items():
                if score > 0.9: # High correlation
                    if f"{other_sym}_buy" in self.open_positions or f"{other_sym}_sell" in self.open_positions:
                         # [OP Roadmap] Stat-Arb Check: If we have an edge on the divergence, allow trade
                         # regardless of correlation block (Mean Reversion of the pair)
                         from ta.patterns.spread import detect_divergence
                         h1 = self.exchange.ohlcv.get(symbol, {}).get("1m", [])
                         h2 = self.exchange.ohlcv.get(other_sym, {}).get("1m", [])
                         div = detect_divergence(h1, h2, score)

                         if div.get('divergence_active') and div['recommended_side'] == side:
                             log.debug(f"STAT-ARB | Overriding correlation block for {symbol} {side}: Z={div['z_score']:.2f}")
                             continue # Allow the trade

                         # Standard block to reduce systemic risk
                         return False

        # Check volume
        book = self.books[symbol]
        bid_vol, ask_vol = book.top_bid_ask_qty()
        if RESTRICT_LIQUIDITY and (bid_vol < 1 or ask_vol < 1):
            return False

        # Check if this specific side is already open or pending
        pos_key = f"{symbol}_{side}"
        if pos_key in self.open_positions or pos_key in self.pending_entries:
            # [TECH-001] Block redundant same-side entry signals.
            # Scaling is handled via manage_position.
            return False

        # [TECH-001] STRATEGY FAMILIES: HEDGING ALLOWED
        # If we have multiple strategies, we allow them to take opposing sides.
        # If we only have ONE strategy (Baseline), we maintain the strict asset-level lock.
        if len(self.strategies) <= 1:
            # [C-002] Asset-level Lock: Prevent simultaneous Long and Short in the same asset
            # unless explicitly allowed by strategy. For HFT safety, we lock the whole asset.
            other_side = "sell" if side == "buy" else "buy"
            other_key = f"{symbol}_{other_side}"
            if other_key in self.open_positions or other_key in self.pending_entries:
                return False

        # [C-005] Dynamic Cooldown check: Scale with volatility (ATR)
        last_exit = self.last_exit_time.get(symbol, 0)
        cooldown = REENTRY_COOLDOWN
        if features and features.get("atr") and features.get("mid"):
            # Scale cooldown down during high volatility to capture moves,
            # and up during low volatility to prevent wash trading.
            atr_pct = features["atr"] / features["mid"]
            # Baseline: 0.1% ATR -> 1.0x cooldown. 0.5% ATR -> 0.2x cooldown.
            scale_factor = max(0.2, min(3.0, 0.001 / (atr_pct + 1e-9)))
            cooldown *= scale_factor

        if time.time() - last_exit < cooldown:
            return False

        return True

    async def _trading_loop(self):
        await asyncio.sleep(5)
        log.info("Trading loop started.")

        # Determine if we should bypass engine-level indicator calculation
        # Global bypass OR if all active strategies opt-out
        engine_indicators_bypassed = getattr(config, 'BYPASS_GLOBAL_FILTERS', False)
        if not engine_indicators_bypassed and self.strategies:
            all_bypassed = True
            for strat in self.strategies:
                 if not getattr(strat, 'params', {}).get('bypass_external_filters', False):
                     all_bypassed = False
                     break
            if all_bypassed:
                engine_indicators_bypassed = True
                log.info("Engine indicators bypassed by all active strategies.")

        # Continue loop even after stop_event until positions clear
        while not self.stop_event.is_set() or self.open_positions or self.pending_entries:
            try:
                # 1. Update Features and Train (Selective)
                all_features = {}
                now = time.time()
                # Ensure each unique symbol is processed only once
                for sym in set(self.enabled_assets + [BTC_SYMBOL]):
                    try:
                        book = self.books[sym]
                        if book.best_bid <= 0 or book.best_ask <= 0:
                            continue

                        current_mid = (book.best_bid + book.best_ask) / 2
                        # [C-001] Track activity based on book timestamp
                        if book.timestamp > 0:
                            self._last_activity[sym] = book.timestamp

                        old_mid = self._last_mid.get(sym)

                        if old_mid is not None and current_mid != old_mid:
                            direction_up = current_mid > old_mid
                            prev_feat = self._last_features.get(sym)
                            if prev_feat is not None:
                                self.model.train_on_tick(sym, prev_feat, direction_up)

                        self._last_mid[sym] = current_mid

                        # [C-001] Event-Driven Optimization: only process if there is activity
                        # or if it's BTC (global confluence), or if we have an open position
                        has_pos = f"{sym}_buy" in self.open_positions or f"{sym}_sell" in self.open_positions
                        last_act = self._last_activity.get(sym, 0)

                        # Process if: BTC, Has Position, or Recent Activity (< 1s ago)
                        if sym == BTC_SYMBOL or has_pos or (now - last_act < 1.0):
                            # Optimization: only get expensive features if we might trade
                            if sym == BTC_SYMBOL or len(self.open_positions) < MAX_CONCURRENT_POSITIONS:
                                 # Skip if BOTH sides are already open or pending
                                 is_full = (f"{sym}_buy" in self.open_positions or f"{sym}_buy" in self.pending_entries) and \
                                           (f"{sym}_sell" in self.open_positions or f"{sym}_sell" in self.pending_entries)
                                 if is_full:
                                     continue

                                 # [TECH-001] Only calculate engine-level features if not bypassed
                                 # Strategies will still use Simulator.get_features as needed.
                                 if engine_indicators_bypassed and sym != BTC_SYMBOL:
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
                                # Scale position
                                await self.exchange.scale_position(sym, pos["side"], pos["qty"])

                # 3. TTL (Time-to-Live) Exit Check
                if getattr(config, "USE_TTL", False):
                    # Convert ACTIVE_TIMEFRAME string (e.g., '5m') to seconds
                    unit = ACTIVE_TIMEFRAME[-1]
                    val = int(ACTIVE_TIMEFRAME[:-1])
                    multiplier_map = {'m': 60, 'H': 3600, 'D': 86400}
                    tf_seconds = val * multiplier_map.get(unit, 60)
                    ttl_limit = tf_seconds * getattr(config, "TTL_CANDLE_MULTIPLIER", 15)

                    if not hasattr(self, "_ttl_logged") or self._ttl_logged != ACTIVE_TIMEFRAME:
                        log.info(f"Dynamic TTL initialized: {ttl_limit}s ({getattr(config, 'TTL_CANDLE_MULTIPLIER', 15)} candles of {ACTIVE_TIMEFRAME})")
                        self._ttl_logged = ACTIVE_TIMEFRAME

                    for pos_key in list(self.open_positions.keys()):
                        pos = self.open_positions[pos_key]
                        if time.time() - pos.get("ts", 0) > ttl_limit:
                            sym = pos_key.split("_")[0]
                            side = pos["side"]
                            # Request TTL Exit from simulator (Mid-price limit exit)
                            if hasattr(self.exchange, "books") and not pos.get("ttl_triggered"):
                                book = self.exchange.books.get(sym)
                                if book:
                                    mid = (book.best_bid + book.best_ask) / 2
                                    log.info(f"TTL EXPIRED for {pos_key} ({time.time() - pos['ts']:.0f}s) | Triggering Limit Exit @ {mid:.8f}")
                                    self.exchange.pending_orders.append({
                                        "symbol": sym, "pos_side": side, "type": "ttl",
                                        "price": mid, "qty": pos["qty"], "is_ttl": True
                                    })
                                    # Mark as triggered but keep in list until simulator reports exit
                                    pos["ttl_triggered"] = True

                # 4. Check Signal and Trade (Skip if shutting down)
                if not self.stop_event.is_set() and (len(self.open_positions) + len(self.pending_entries)) < MAX_CONCURRENT_POSITIONS:
                    for sym in self.enabled_assets:
                        # Re-check limit inside loop to avoid burst over-trading
                        if (len(self.open_positions) + len(self.pending_entries)) >= MAX_CONCURRENT_POSITIONS:
                            break

                        book = self.books[sym]
                        if book.best_bid <= 0: continue

                        # Only predict if we don't have BOTH sides open
                        if f"{sym}_buy" in self.open_positions and f"{sym}_sell" in self.open_positions:
                            continue

                        feat = all_features.get(sym)

                        # USE PLUGGABLE STRATEGY IF AVAILABLE
                        market_data = {"symbol": sym, "book": book, "equity": self.equity, "features": feat}

                        # [TECH-001] Support for multiple strategies in a Family
                        active_signals = []
                        if self.strategies:
                            for strat in self.strategies:
                                # [TECH-001] AUTHENTICITY GUARD: Check if strategy is ready
                                if hasattr(strat, "is_ready") and not strat.is_ready(sym):
                                    if not hasattr(self, "_warmup_logged"): self._warmup_logged = {}
                                    now = time.time()
                                    if now - self._warmup_logged.get(f"{sym}_{strat.name}", 0) > 60: # Log every minute
                                        log.info(f"{sym}: {strat.get_readiness_eta(sym)}")
                                        self._warmup_logged[f"{sym}_{strat.name}"] = now
                                    continue

                                sig = strat.get_entry_signal(market_data)
                                if sig:
                                    # Ensure signal knows who sent it
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
                            # Skip if a position in this direction is already open
                            if f"{sym}_{side}" in self.open_positions:
                                continue

                            if not self._asset_is_tradable(sym, side, features=feat, signal=signal):
                                continue

                            qty = signal["qty"]
                            entry = signal["entry_price"]
                            stop = signal["stop_price"]
                            tp = signal["exit_price"]
                            btc_conf = signal["btc_confluence"]
                            orig_side = signal.get("original_side", side)
                            is_contr = signal.get("is_contrarian", False)

                            # Immediate local registration to prevent race condition
                            pos_key = f"{sym}_{side}"
                            self.pending_entries.add(pos_key)

                            side_str = side.upper()
                            if is_contr:
                                side_str = f"{orig_side.upper()} [Flipped to {side.upper()}]"

                            # Extract all feature keys (excluding common ones handled manually in log)
                            exclude = ['side', 'entry_price', 'exit_price', 'stop_price', 'qty', 'confidence', 'btc_confluence', 'original_side', 'is_contrarian', 'rsi', 'drt', 'drt_f', 'drt_s', 'vol_pct', 'strategy_id', 'symbol', 'features']
                            extra_features = {k: v for k, v in signal.items() if k not in exclude and v is not None}
                            feat_msg = " ".join([f"{k}={v}" for k, v in extra_features.items()])

                            signal_msg = (f"SIGNAL: {sym} {side_str} [Strat: {signal.get('strategy_id')}] qty={qty:.3f} "
                                          f"entry={entry:.8f} exit={tp:.8f} stop={stop:.8f} "
                                          f"[{btc_conf}] drt_f={signal.get('drt_f')} drt_s={signal.get('drt_s')} rsi={signal.get('rsi',50):.1f} "
                                          f"macd={signal.get('macd',0):.4f} vol={signal.get('vol_pct',0):.2f} {feat_msg} equity={self.equity:.2f}")

                            # Save to database
                            if getattr(self.exchange, "db", None):
                                self.exchange.db.save_signal(sym, side, entry, signal)

                            # Always log for DB, but conditionally for console
                            if LOG_SIGNALS:
                                log.info(signal_msg)
                            else:
                                # [TECH-001] Keep signal details in Shadow Log/DB only
                                log.debug(signal_msg)

                            # Final collision check immediately before router call
                            if not self._asset_is_tradable(sym, side, features=feat):
                                if pos_key in self.open_positions: del self.open_positions[pos_key]
                                if pos_key in self.pending_entries: self.pending_entries.remove(pos_key)
                                continue

                            # Add regime to features for predict logic
                            feat["asset_regime"] = self.asset_regimes.get(sym, "stable")

                            # [TECH-001] Merge all calculated features into the signal
                            # to satisfy requirement (g) for full metrics reporting.
                            if feat:
                                for k, v in feat.items():
                                    if k not in signal:
                                        signal[k] = v

                            # Inject extra info for router/exchange
                            signal.update({
                                "symbol": sym,
                                "features": feat
                            })

                            resp = await self.router.route_signal(signal)
                            if resp.get("code") == "00000" and not LOG_SIGNALS:
                                # Show signal with fill/place if LOG_SIGNALS is False
                                log.info(f"Entry Triggered | {signal_msg}")

                            if resp.get("code") != "00000":
                                # Reject local registration if exchange fails
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
            await asyncio.sleep(SUMMARY_INTERVAL_SECONDS)

    def _log_periodic_summary(self):
        win_rate = self.winning_trades / self.total_trades * 100 if self.total_trades > 0 else 0
        tp_win_pct = self.tp_wins / self.total_trades * 100 if self.total_trades > 0 else 0
        drawdown = (1 - self.equity / self.peak_equity) * 100 if self.peak_equity > 0 else 0
        roi = (self.equity / self.starting_equity - 1) * 100
        used_margin = getattr(self.exchange, "used_margin", 0)
        log.info(f"SUMMARY | Equity: {self.equity:.2f} | ROI: {roi:.1f}% | "
                 f"Trades: {self.total_trades} | Win%: {win_rate:.1f} (TP: {tp_win_pct:.1f}%) | "
                 f"Open: {len(self.open_positions)} | Margin: {used_margin:.2f}")
