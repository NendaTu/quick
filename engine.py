import asyncio, time, logging, math
from typing import Dict, Set
from config import *
from orderbook import OrderBook
from simulator import Simulator
from models import LearningModel, DummyModel

log = logging.getLogger("scalper.engine")

class Engine:
    def __init__(self):
        self.books: Dict[str, OrderBook] = {}
        self.leverage_limits = {}
        self.pending_entries: Set[str] = set() # key is 'SYMBOL_buy' or 'SYMBOL_sell'
        self.equity = INITIAL_EQUITY
        self.starting_equity = INITIAL_EQUITY
        self.peak_equity = INITIAL_EQUITY

        # open_positions key is 'SYMBOL_buy' or 'SYMBOL_sell'
        self.open_positions: Dict[str, dict] = {}
        self.enabled_assets: List[str] = []

        self.total_trades = 0
        self.winning_trades = 0 # Cumulative Wins (TP + BE)
        self.tp_wins = 0        # Direct TP hits
        self.be_wins = 0        # Breakeven protected wins
        self.losing_trades = 0
        self.cumulative_pnl = 0.0

        # Performance tracking
        self.asset_stats: Dict[str, Dict[str, any]] = {}
        self.last_exit_time: Dict[str, float] = {}

        self._last_mid = {}
        self._last_features = {}

        self.stop_event = asyncio.Event()
        self.start_time = None

        if MODE == "paper":
            self.exchange = Simulator()
            self.exchange.engine = self
            self.model = LearningModel(self.exchange)
        else:
            self.exchange = None
            self.model = DummyModel()
            log.warning("Live/testnet mode not implemented")

    async def start(self):
        self.start_time = time.time()

        # Handle signals for graceful manual shutdown
        try:
            import signal
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, lambda: self.stop_event.set())
        except Exception as e:
            log.debug(f"Signal handlers not supported: {e}")

        if MODE == "paper":
            await self.exchange.warm_up()
            self.leverage_limits = self.exchange.get_leverage_limits()
            self.enabled_assets = self.exchange.discovered_assets
            # Initialize books for discovered assets
            for sym in self.enabled_assets + [BTC_SYMBOL]:
                self.books[sym] = OrderBook(sym)
            log.info(f"Dynamic Initialization: {len(self.enabled_assets)} assets discovered and loaded.")
        else:
            log.error("Only paper mode is implemented.")
            return

        asyncio.create_task(self.exchange.data_feed_task(self))
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
            self.equity = self.exchange.equity

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
                if hasattr(self.exchange, "db"):
                    self.exchange.db.purge_old_data()
                await asyncio.sleep(3600)
            except Exception as e:
                log.error(f"Maintenance error: {e}")
                await asyncio.sleep(60)

    def _report_entry(self, symbol: str, side: str, qty: float, entry: float, orig_side: str = None, is_contr: bool = False):
        pos_key = f"{symbol}_{side}"
        # If orig_side not passed (e.g. from simulator), default to current
        if orig_side is None: orig_side = side
        self.open_positions[pos_key] = {
            "side": side, "qty": qty, "entry": entry,
            "orig_side": orig_side, "is_contr": is_contr,
            "ts": time.time()
        }
        if pos_key in self.pending_entries:
            self.pending_entries.remove(pos_key)

    def _report_exit(self, symbol: str, side: str, round_trip_pnl: float, exit_type: str = "unknown", is_be: bool = False):
        # Local registration cleanup
        pos_key = f"{symbol}_{side}"
        if pos_key in self.open_positions:
            del self.open_positions[pos_key]

        # Also ensure it's cleared from pending if it was an entry failure
        if pos_key in self.pending_entries:
            self.pending_entries.remove(pos_key)

        self.last_exit_time[symbol] = time.time()

        self.total_trades += 1
        self.cumulative_pnl += round_trip_pnl

        # Asset-specific stats
        if symbol not in self.asset_stats:
            self.asset_stats[symbol] = {"buy_wins": 0, "buy_losses": 0, "sell_wins": 0, "sell_losses": 0, "pnl": 0.0, "tp_wins": 0, "be_wins": 0}

        self.asset_stats[symbol]["pnl"] += round_trip_pnl

        if round_trip_pnl > 0:
            self.winning_trades += 1
            if exit_type == "tp":
                self.tp_wins += 1
                self.asset_stats[symbol]["tp_wins"] += 1
            elif is_be:
                self.be_wins += 1
                self.asset_stats[symbol]["be_wins"] += 1

            if side == "buy": self.asset_stats[symbol]["buy_wins"] += 1
            else: self.asset_stats[symbol]["sell_wins"] += 1
        else:
            if exit_type == "tp":
                log.warning(f"GROSS WIN / NET LOSS on {symbol}: PnL={round_trip_pnl:.4f} (fees consumed profit)")
            self.losing_trades += 1
            if side == "buy": self.asset_stats[symbol]["buy_losses"] += 1
            else: self.asset_stats[symbol]["sell_losses"] += 1

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

    def _asset_is_tradable(self, symbol: str, side: str) -> bool:
        # Check volume
        book = self.books[symbol]
        bid_vol, ask_vol = book.top_bid_ask_qty()
        if RESTRICT_LIQUIDITY and (bid_vol < 1 or ask_vol < 1):
            return False

        # Check if this specific side is already open or pending
        pos_key = f"{symbol}_{side}"
        if pos_key in self.open_positions or pos_key in self.pending_entries:
            return False

        # Cooldown check
        last_exit = self.last_exit_time.get(symbol, 0)
        if time.time() - last_exit < REENTRY_COOLDOWN:
            return False

        return True

    async def _trading_loop(self):
        await asyncio.sleep(5)
        log.info("Trading loop started.")

        # Continue loop even after stop_event until positions clear
        while not self.stop_event.is_set() or self.open_positions or self.pending_entries:
            try:
                # 1. Update Features and Train (Selective)
                all_features = {}
                # Ensure each unique symbol is processed only once
                for sym in set(self.enabled_assets + [BTC_SYMBOL]):
                    try:
                        book = self.books[sym]
                        if book.best_bid <= 0 or book.best_ask <= 0:
                            continue

                        current_mid = (book.best_bid + book.best_ask) / 2
                        old_mid = self._last_mid.get(sym)

                        if old_mid is not None and current_mid != old_mid:
                            direction_up = current_mid > old_mid
                            prev_feat = self._last_features.get(sym)
                            if prev_feat is not None:
                                self.model.train_on_tick(sym, prev_feat, direction_up)

                        self._last_mid[sym] = current_mid

                        # Optimization: only get expensive features if we might trade
                        # or for BTC (global confluence)
                        if sym == BTC_SYMBOL or len(self.open_positions) < MAX_CONCURRENT_POSITIONS:
                             # Skip if BOTH sides are already open or pending
                             is_full = (f"{sym}_buy" in self.open_positions or f"{sym}_buy" in self.pending_entries) and \
                                       (f"{sym}_sell" in self.open_positions or f"{sym}_sell" in self.pending_entries)
                             if is_full:
                                 continue

                             feat = self.exchange.get_features(sym)
                             self._last_features[sym] = feat
                             all_features[sym] = feat
                    except Exception as e:
                        log.error(f"Feature calculation error for {sym}: {e}")

                # 3. TTL (Time-to-Live) Exit Check
                for pos_key in list(self.open_positions.keys()):
                    pos = self.open_positions[pos_key]
                    if time.time() - pos.get("ts", 0) > TRADE_TTL_SECONDS:
                        sym = pos_key.split("_")[0]
                        side = pos["side"]
                        # Request TTL Exit from simulator (Mid-price limit exit)
                        if hasattr(self.exchange, "books") and not pos.get("ttl_triggered"):
                            book = self.exchange.books.get(sym)
                            if book:
                                mid = (book.best_bid + book.best_ask) / 2
                                log.info(f"TTL EXPIRED for {pos_key} ({time.time() - pos['ts']:.0f}s) | Triggering Limit Exit @ {mid:.8f}")
                                self.exchange.pending_orders.append({
                                    "symbol": sym, "pos_side": side, "type": "tp",
                                    "price": mid, "qty": pos["qty"], "is_ttl": True
                                })
                                # Mark as triggered but keep in list until simulator reports exit
                                pos["ttl_triggered"] = True

                # 4. Check Signal and Trade (Skip if shutting down)
                if not self.stop_event.is_set() and len(self.open_positions) < MAX_CONCURRENT_POSITIONS:
                    for sym in self.enabled_assets:
                        # Re-check limit inside loop to avoid burst over-trading
                        if len(self.open_positions) >= MAX_CONCURRENT_POSITIONS:
                            break

                        book = self.books[sym]
                        if book.best_bid <= 0: continue

                        # Only predict if we don't have BOTH sides open
                        if f"{sym}_buy" in self.open_positions and f"{sym}_sell" in self.open_positions:
                            continue

                        feat = all_features.get(sym)
                        signal = self.model.predict(sym, book, self.equity, features=feat)
                        if signal is None:
                            continue

                        side = signal["side"]
                        # Skip if a position in this direction is already open
                        if f"{sym}_{side}" in self.open_positions:
                            continue

                        if not self._asset_is_tradable(sym, side):
                            continue

                        qty = signal["qty"]
                        entry = signal["entry_price"]
                        stop = signal["stop_price"]
                        tp = signal["exit_price"]
                        btc_conf = signal["btc_confluence"]
                        drt = signal.get("drt", 0.5)
                        orig_side = signal.get("original_side", side)
                        is_contr = signal.get("is_contrarian", False)

                        # Immediate local registration to prevent race condition
                        pos_key = f"{sym}_{side}"
                        if ENTRY_ORDER_TYPE == "market":
                            self.open_positions[pos_key] = {"side": side, "qty": qty, "entry": entry, "orig_side": orig_side, "is_contr": is_contr}
                        else:
                            self.pending_entries.add(pos_key)

                        side_str = side.upper()
                        if is_contr:
                            side_str = f"{orig_side.upper()} [Flipped to {side.upper()}]"

                        signal_msg = (f"SIGNAL: {sym} {side_str} qty={qty:.3f} "
                                      f"entry={entry:.8f} exit={tp:.8f} stop={stop:.8f} "
                                      f"[{btc_conf}] drt_f={signal.get('drt_f')} drt_s={signal.get('drt_s')} rsi={signal.get('rsi',50):.1f} "
                                      f"macd={signal.get('macd',0):.4f} vol={signal.get('vol_pct',0):.2f} equity={self.equity:.2f}")

                        # Always log for DB, but conditionally for console
                        if LOG_SIGNALS:
                            log.info(signal_msg)
                        else:
                            log.debug(signal_msg)

                        resp = self.exchange.place_trade_oco(sym, side, qty, entry, stop, tp, btc_conf, drt, original_side=orig_side, is_contrarian=is_contr)
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
