import asyncio, time, logging, math
from typing import Dict
from config import *
from orderbook import OrderBook
from simulator import Simulator
from models import LearningModel, DummyModel

log = logging.getLogger("scalper.engine")

class Engine:
    def __init__(self):
        self.books: Dict[str, OrderBook] = {sym: OrderBook(sym) for sym in ASSETS + [BTC_SYMBOL]}
        self.leverage_limits = {}
        self.equity = INITIAL_EQUITY
        self.starting_equity = INITIAL_EQUITY
        self.peak_equity = INITIAL_EQUITY
        self.open_positions: Dict[str, dict] = {}
        self.enabled_assets = set(ASSETS)

        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0
        self.cumulative_pnl = 0.0

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
        self.leverage_limits = self.exchange.get_leverage_limits()
        log.info(f"Leverage limits: {self.leverage_limits}")

        if MODE != "paper":
            log.error("Only paper mode is implemented.")
            return

        asyncio.create_task(self.exchange.data_feed_task(self))
        asyncio.create_task(self._equity_monitor())
        asyncio.create_task(self._trading_loop())

        await self.stop_event.wait()
        log.info("Bot stopped.")
        self._print_final_stats()

    async def _equity_monitor(self):
        while not self.stop_event.is_set():
            if self.peak_equity > 0 and self.equity <= DRAWDOWN_LIMIT * self.peak_equity:
                log.critical(f"DRAWDOWN LIMIT HIT: equity={self.equity:.2f}, peak={self.peak_equity:.2f}")
                self.stop_event.set()
            await asyncio.sleep(0.5)

    def _update_stats(self, round_trip_pnl: float):
        self.total_trades += 1
        self.cumulative_pnl += round_trip_pnl
        if round_trip_pnl > 0:
            self.winning_trades += 1
        else:
            self.losing_trades += 1

    def _print_final_stats(self):
        elapsed = time.time() - self.start_time if self.start_time else 0
        hours, rem = divmod(elapsed, 3600)
        minutes, seconds = divmod(rem, 60)
        win_rate = self.winning_trades / self.total_trades * 100 if self.total_trades > 0 else 0
        log.info(f"===== FINAL STATS =====")
        log.info(f"Session duration: {int(hours)}h {int(minutes)}m {int(seconds)}s")
        log.info(f"Total trades: {self.total_trades}")
        log.info(f"Wins: {self.winning_trades}, Losses: {self.losing_trades}")
        log.info(f"Win rate: {win_rate:.1f}%")
        log.info(f"Cumulative PnL: {self.cumulative_pnl:.2f} USDT")
        log.info(f"Final equity: {self.equity:.2f} USDT")
        log.info(f"Peak equity: {self.peak_equity:.2f} USDT")

    def _asset_is_tradable(self, symbol: str) -> bool:
        book = self.books[symbol]
        bid_vol, ask_vol = book.top_bid_ask_qty()
        if bid_vol < 500 or ask_vol < 500:
            return False
        if symbol in self.open_positions:
            return False
        return True

    async def _trading_loop(self):
        await asyncio.sleep(3)
        last_summary_time = time.time()

        while not self.stop_event.is_set():
            try:
                for sym in ASSETS + [BTC_SYMBOL]:
                    book = self.books[sym]
                    if book.best_bid <= 0 or book.best_ask <= 0:
                        continue
                    current_mid = (book.best_bid + book.best_ask) / 2
                    old_mid = self._last_mid.get(sym)
                    if old_mid is not None:
                        direction_up = current_mid > old_mid
                        prev_feat = self._last_features.get(sym)
                        if prev_feat is not None:
                            self.model.train_on_tick(sym, prev_feat, direction_up)
                            self.model.add_tick(sym, prev_feat, direction_up)
                    self._last_mid[sym] = current_mid
                    self._last_features[sym] = self.exchange.get_features(sym)

                for sym in ASSETS:
                    if sym not in self.open_positions:
                        self.enabled_assets.add(sym)

                active = [s for s in ASSETS if s in self.enabled_assets and self._asset_is_tradable(s)]
                if len(self.open_positions) >= MAX_CONCURRENT_POSITIONS:
                    active = []

                for sym in active:
                    book = self.books[sym]
                    signal = self.model.predict(sym, book, self.equity)
                    if signal is None:
                        continue

                    side = signal["side"]
                    qty = signal["qty"]
                    entry = signal["entry_price"]
                    stop = signal["stop_price"]
                    tp = signal["exit_price"]

                    log.info(f"SIGNAL: {sym} {side.upper()} qty={qty:.3f} "
                             f"entry={entry:.4f} exit={tp:.4f} stop={stop:.4f} "
                             f"drt={signal.get('drt',0):.3f} rsi={signal.get('rsi',50):.1f} "
                             f"macd={signal.get('macd',0):.4f} ema={signal.get('ema_short',0):.4f} "
                             f"vol={signal.get('vol_pct',0):.2f} equity={self.equity:.2f}")
                    self.exchange.place_trade_oco(sym, side, qty, entry, stop, tp)
                    self.enabled_assets.discard(sym)

                if self.equity > self.peak_equity:
                    self.peak_equity = self.equity

                now = time.time()
                if now - last_summary_time >= 10.0:
                    self._log_periodic_summary()
                    last_summary_time = now

                await asyncio.sleep(0.2)
            except Exception as e:
                log.exception(f"Trading loop error: {e}")
                await asyncio.sleep(1)

    def _log_periodic_summary(self):
        win_rate = self.winning_trades / self.total_trades * 100 if self.total_trades > 0 else 0
        drawdown = (1 - self.equity / self.peak_equity) * 100 if self.peak_equity > 0 else 0
        log.info(f"SUMMARY | Equity: {self.equity:.2f} | Peak: {self.peak_equity:.2f} | "
                 f"Drawdown: {drawdown:.1f}% | Trades: {self.total_trades} | "
                 f"Win%: {win_rate:.1f} | Open: {len(self.open_positions)}")