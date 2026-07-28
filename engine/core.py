"""
1. Summary: Unified trading engine core and modular composition manager.
2. Description: Instantiates PositionLedger, RiskGate, TradeReporter, RegimeClassifier, ExchangeSync, and TradingLoop sub-components. Exposes delegated property interfaces to preserve 100% backward compatibility.
3. Context: Primary package core coordinated by main.py and compare.py.
"""
import asyncio
import time
import logging
from typing import Dict, Set, List, Optional

import config
from orderbook import OrderBook
from models import LearningModel, DummyModel
from engine.entry import SignalRouter

# Modular components
from engine.positions import PositionLedger
from engine.risk import RiskGate
from engine.reporting import TradeReporter
from engine.regimes import RegimeClassifier
from engine.reconciliation import ExchangeSync
from engine.loop import TradingLoop

log = logging.getLogger("scalper.engine")

class Engine:
    def __init__(self, use_db=True, mode=None, config_context=None, config_overrides=None):
        if config_context is not None:
            self.config = config_context
        else:
            self.config = config.ConfigContext(**(config_overrides or {}))
        self.mode = (mode or self.config.MODE).lower().strip(' "').strip("'")

        self.books: Dict[str, OrderBook] = {}
        self.leverage_limits = {}
        self.enabled_assets: List[str] = []
        self.strategies: List[Any] = []
        self.session_signals = 0
        self.stop_event = asyncio.Event()
        self.start_time = time.time()

        # 1. Instantiate modular subcomponents (P1-1)
        self.ledger = PositionLedger()
        self.risk = RiskGate(self.config)
        self.reporter = TradeReporter(self.config.INITIAL_EQUITY)
        self.regime = RegimeClassifier()

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

        # 2. Wire up exchange synchronization and operational loops via constructor injection (P1-1)
        self.sync = ExchangeSync(
            exchange=self.exchange,
            ledger=self.ledger,
            config=self.config,
            leverage_limits=self.leverage_limits,
            books=self.books,
            report_exit_func=self._report_exit,
            last_price=self.exchange.last_price if hasattr(self.exchange, "last_price") else {}
        )

        self.loop = TradingLoop(
            engine=self,
            ledger=self.ledger,
            risk=self.risk,
            reporter=self.reporter,
            regime=self.regime,
            sync=self.sync,
            exchange=self.exchange,
            router=self.router,
            config_context=self.config
        )

    # --- Property Delegations for 100% Backward Compatibility ---
    @property
    def open_positions(self):
        return self.ledger.open_positions
    @open_positions.setter
    def open_positions(self, val):
        self.ledger.open_positions = val

    @property
    def pending_entries(self):
        return self.ledger.pending_entries
    @pending_entries.setter
    def pending_entries(self, val):
        self.ledger.pending_entries = val

    @property
    def equity(self):
        return self.reporter.equity
    @equity.setter
    def equity(self, val):
        self.reporter.equity = val

    @property
    def starting_equity(self):
        return self.reporter.starting_equity
    @starting_equity.setter
    def starting_equity(self, val):
        self.reporter.starting_equity = val

    @property
    def peak_equity(self):
        return self.reporter.peak_equity
    @peak_equity.setter
    def peak_equity(self, val):
        self.reporter.peak_equity = val

    @property
    def total_trades(self):
        return self.reporter.total_trades
    @total_trades.setter
    def total_trades(self, val):
        self.reporter.total_trades = val

    @property
    def winning_trades(self):
        return self.reporter.winning_trades
    @winning_trades.setter
    def winning_trades(self, val):
        self.reporter.winning_trades = val

    @property
    def tp_wins(self):
        return self.reporter.tp_wins
    @tp_wins.setter
    def tp_wins(self, val):
        self.reporter.tp_wins = val

    @property
    def be_wins(self):
        return self.reporter.be_wins
    @be_wins.setter
    def be_wins(self, val):
        self.reporter.be_wins = val

    @property
    def losing_trades(self):
        return self.reporter.losing_trades
    @losing_trades.setter
    def losing_trades(self, val):
        self.reporter.losing_trades = val

    @property
    def cumulative_pnl(self):
        return self.reporter.cumulative_pnl
    @cumulative_pnl.setter
    def cumulative_pnl(self, val):
        self.reporter.cumulative_pnl = val

    @property
    def gross_profit(self):
        return self.reporter.gross_profit
    @gross_profit.setter
    def gross_profit(self, val):
        self.reporter.gross_profit = val

    @property
    def gross_loss(self):
        return self.reporter.gross_loss
    @gross_loss.setter
    def gross_loss(self, val):
        self.reporter.gross_loss = val

    @property
    def asset_stats(self):
        return self.reporter.asset_stats
    @asset_stats.setter
    def asset_stats(self, val):
        self.reporter.asset_stats = val

    @property
    def strategy_stats(self):
        return self.reporter.strategy_stats
    @strategy_stats.setter
    def strategy_stats(self, val):
        self.reporter.strategy_stats = val

    @property
    def equity_history(self):
        return self.reporter.equity_history
    @equity_history.setter
    def equity_history(self, val):
        self.reporter.equity_history = val

    @property
    def asset_regimes(self):
        return self.regime.asset_regimes
    @asset_regimes.setter
    def asset_regimes(self, val):
        self.regime.asset_regimes = val

    @property
    def last_exit_time(self):
        return self.risk.last_exit_time
    @last_exit_time.setter
    def last_exit_time(self, val):
        self.risk.last_exit_time = val

    @property
    def pos_pnl(self):
        return self.reporter.pos_pnl
    @pos_pnl.setter
    def pos_pnl(self, val):
        self.reporter.pos_pnl = val

    @property
    def profit_ratio(self) -> float:
        return self.reporter.profit_ratio

    # --- Core Operation Delegation ---
    async def start(self, preloaded_data=None, external_feed=None):
        await self.loop.run(preloaded_data=preloaded_data, external_feed=external_feed)

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

    def _write_signals_log(self, symbol: str, side: str, strategy_id: str, scoring_result: dict):
        from tools.logger import setup_signals_logging
        setup_signals_logging(self.start_time, symbol, side, strategy_id, scoring_result)

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

        if pos_key in self.ledger.open_positions:
            p = self.ledger.open_positions[pos_key]
            total_qty = p["qty"] + qty
            p["entry"] = (p["entry"] * p["qty"] + entry * qty) / total_qty
            p["qty"] = total_qty
            p["margin"] += margin
            if stop_price: p["stop_price"] = stop_price
            if tp_price: p["tp_price"] = tp_price
            if tp1_price: p["tp1_price"] = tp1_price
            if tp1_qty: p["tp1_qty"] = tp1_qty
        else:
            self.ledger.open_positions[pos_key] = {
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
        if pos_key in self.ledger.pending_entries:
            self.ledger.pending_entries.remove(pos_key)

        if hasattr(self.exchange, "db"):
            self.exchange.db.save_trade(strategy_id, symbol, side, entry_ts, entry, qty)

    def _report_exit(self, symbol: str, side: str, round_trip_pnl: float, exit_type: str = "unknown", is_be: bool = False, is_partial: bool = False, features: dict = None, margin: float = 0):
        pos_key = f"{symbol}_{side}"

        if not is_partial and features:
            self.model.train_on_trade(symbol, features, round_trip_pnl)

        if self.config.USE_VIRTUAL_BALANCE or self.mode == "paper":
            self.reporter.equity += round_trip_pnl
            self.equity = self.reporter.equity # Keep synced

        self.reporter.cumulative_pnl += round_trip_pnl

        if round_trip_pnl > 0:
            self.reporter.gross_profit += round_trip_pnl
        else:
            self.reporter.gross_loss += abs(round_trip_pnl)

        self.reporter.equity_history.append({
            "ts": time.time(),
            "equity": self.reporter.equity,
            "pnl": round_trip_pnl,
            "symbol": symbol
        })

        if hasattr(self.exchange, "db"):
            entry_ts = 0
            entry_price = 0
            qty = 0
            strategy_id = "model"
            if pos_key in self.ledger.open_positions:
                p = self.ledger.open_positions[pos_key]
                entry_ts = p["ts"]
                entry_price = p["entry"]
                qty = p["qty"]
                strategy_id = p.get("strategy_id", "model")

            self.exchange.db.save_trade(
                strategy_id, symbol, side, entry_ts, entry_price, qty,
                exit_ts=time.time(), exit_price=self.exchange.last_price.get(symbol),
                pnl=round_trip_pnl, exit_type=exit_type
            )

        if symbol not in self.reporter.asset_stats:
            self.reporter.asset_stats[symbol] = {
                "buy_wins": 0, "buy_losses": 0, "sell_wins": 0, "sell_losses": 0,
                "pnl": 0.0, "tp_wins": 0, "be_wins": 0, "buy_pnl": 0.0, "sell_pnl": 0.0,
                "total_margin": 0.0
            }

        self.reporter.asset_stats[symbol]["total_margin"] += margin
        self.reporter.asset_stats[symbol]["pnl"] += round_trip_pnl
        if side == "buy": self.reporter.asset_stats[symbol]["buy_pnl"] += round_trip_pnl
        else: self.reporter.asset_stats[symbol]["sell_pnl"] += round_trip_pnl

        strategy_id = "model"
        if pos_key in self.ledger.open_positions:
            strategy_id = self.ledger.open_positions[pos_key].get("strategy_id", "model")

        if strategy_id not in self.reporter.strategy_stats:
            self.reporter.strategy_stats[strategy_id] = {
                "buy_wins": 0, "buy_losses": 0, "sell_wins": 0, "sell_losses": 0,
                "pnl": 0.0, "tp_wins": 0, "be_wins": 0, "total_trades": 0
            }

        self.reporter.strategy_stats[strategy_id]["pnl"] += round_trip_pnl
        self.reporter.pos_pnl[pos_key] = self.reporter.pos_pnl.get(pos_key, 0.0) + round_trip_pnl

        if is_partial:
            return

        total_trade_pnl = self.reporter.pos_pnl.pop(pos_key, 0.0)
        self.reporter.total_trades += 1
        self.reporter.strategy_stats[strategy_id]["total_trades"] += 1

        if pos_key in self.ledger.open_positions:
            del self.ledger.open_positions[pos_key]

        if pos_key in self.ledger.pending_entries:
            self.ledger.pending_entries.remove(pos_key)

        self.risk.last_exit_time[symbol] = self.get_current_time(symbol)

        if total_trade_pnl > 0:
            self.reporter.winning_trades += 1
            if exit_type == "tp":
                self.reporter.tp_wins += 1
                self.reporter.asset_stats[symbol]["tp_wins"] += 1
                self.reporter.strategy_stats[strategy_id]["tp_wins"] += 1
            elif is_be:
                self.reporter.be_wins += 1
                self.reporter.asset_stats[symbol]["be_wins"] += 1
                self.reporter.strategy_stats[strategy_id]["be_wins"] += 1

            if side == "buy":
                self.reporter.asset_stats[symbol]["buy_wins"] += 1
                self.reporter.strategy_stats[strategy_id]["buy_wins"] += 1
            else:
                self.reporter.asset_stats[symbol]["sell_wins"] += 1
                self.reporter.strategy_stats[strategy_id]["sell_wins"] += 1
        else:
            if exit_type in ["tp", "ttl"]:
                log.warning(f"GROSS WIN / NET LOSS on {symbol} [{exit_type.upper()}]: PnL={total_trade_pnl:.4f} (fees consumed profit)")
            self.reporter.losing_trades += 1
            if side == "buy":
                self.reporter.asset_stats[symbol]["buy_losses"] += 1
                self.reporter.strategy_stats[strategy_id]["buy_losses"] += 1
            else:
                self.reporter.asset_stats[symbol]["sell_losses"] += 1
                self.reporter.strategy_stats[strategy_id]["sell_losses"] += 1

    def _print_final_stats(self):
        elapsed = time.time() - self.start_time if self.start_time else 0
        self.reporter.print_final_stats(elapsed)

    def _classify_asset_regimes(self, symbol=None):
        self.regime.classify_asset_regimes(symbol=symbol, exchange=self.exchange, enabled_assets=self.enabled_assets)

    def _asset_is_tradable(self, symbol: str, side: str, features: dict = None, signal: dict = None) -> bool:
        return self.risk.is_asset_tradable(
            symbol=symbol,
            side=side,
            equity=self.reporter.equity,
            open_positions=self.ledger.open_positions,
            pending_entries=self.ledger.pending_entries,
            leverage_limits=self.leverage_limits,
            exchange=self.exchange,
            books=self.books,
            features=features,
            signal=signal,
            get_current_time_func=self.get_current_time,
            strategies_count=len(self.strategies)
        )

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

    def _log_periodic_summary(self):
        win_rate = self.winning_trades / self.total_trades * 100 if self.total_trades > 0 else 0
        tp_win_pct = self.tp_wins / self.total_trades * 100 if self.total_trades > 0 else 0
        drawdown = (1 - self.equity / self.peak_equity) * 100 if self.peak_equity > 0 else 0
        roi = (self.equity / self.starting_equity - 1) * 100
        used_margin = getattr(self.exchange, "used_margin", 0)
        log.info(f"SUMMARY | Equity: {self.equity:.2f} | ROI: {roi:.1f}% | "
                 f"Trades: {self.total_trades} | Win%: {win_rate:.1f} (TP: {tp_win_pct:.1f}%) | "
                 f"Open: {len(self.open_positions)} | Margin: {used_margin:.2f}")

    async def _sync_exchange_state(self):
        await self.sync.sync_exchange_state()
