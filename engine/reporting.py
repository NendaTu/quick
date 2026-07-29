"""
1. Summary: Specialized stats tracking and performance reporting subsystem.
2. Description: Aggregates real-time trade results, win rates, drawdowns, gross profits, and compounding curves. Dispatches formatted console logs summarizing performance metrics by asset and strategy.
3. Context: Injected into the core loops to capture execution results statelessly and finalize runs with detailed audits.
"""
import time
import logging
from typing import Dict, List, Any, Optional

log = logging.getLogger("scalper.engine.reporting")

class TradeReporter:
    def __init__(self, starting_equity: float = 40.0):
        self.starting_equity = starting_equity
        self.equity = starting_equity
        self.peak_equity = starting_equity

        self.total_trades = 0
        self.winning_trades = 0
        self.tp_wins = 0
        self.be_wins = 0
        self.losing_trades = 0
        self.cumulative_pnl = 0.0
        self.gross_profit = 0.0
        self.gross_loss = 0.0

        self.asset_stats: Dict[str, Dict[str, Any]] = {}
        self.strategy_stats: Dict[str, Dict[str, Any]] = {}
        self.equity_history: List[dict] = []
        self.pos_pnl: Dict[str, float] = {}

    @property
    def profit_ratio(self) -> float:
        if self.gross_loss > 0:
            return self.gross_profit / self.gross_loss
        return float('inf') if self.gross_profit > 0 else 1.0

    def record_entry(self, symbol: str, side: str, qty: float, entry: float, margin: float, strategy_id: str):
        """
        Symmetrically registers a trade entry fact in TradeReporter (R1-1).
        Currently acts as a placeholder / stats tracking point for entries.
        """
        pass

    def record_exit(self, symbol: str, side: str, round_trip_pnl: float, exit_type: str = "unknown",
                    is_be: bool = False, is_partial: bool = False, margin: float = 0.0, strategy_id: str = "model",
                    use_virtual_balance_or_paper: bool = True) -> Optional[float]:
        """
        Registers a trade exit fact in TradeReporter and updates stats, completely decoupled
        from database persistence, models, or active trading/cooldown logic (R1-1, R1-5).
        Returns total_trade_pnl for the completed trade, or None if it is a partial exit.
        """
        if use_virtual_balance_or_paper:
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

        if symbol not in self.asset_stats:
            self.asset_stats[symbol] = {
                "buy_wins": 0, "buy_losses": 0, "sell_wins": 0, "sell_losses": 0,
                "pnl": 0.0, "tp_wins": 0, "be_wins": 0, "buy_pnl": 0.0, "sell_pnl": 0.0,
                "total_margin": 0.0
            }

        self.asset_stats[symbol]["total_margin"] += margin
        self.asset_stats[symbol]["pnl"] += round_trip_pnl
        if side == "buy":
            self.asset_stats[symbol]["buy_pnl"] += round_trip_pnl
        else:
            self.asset_stats[symbol]["sell_pnl"] += round_trip_pnl

        if strategy_id not in self.strategy_stats:
            self.strategy_stats[strategy_id] = {
                "buy_wins": 0, "buy_losses": 0, "sell_wins": 0, "sell_losses": 0,
                "pnl": 0.0, "tp_wins": 0, "be_wins": 0, "total_trades": 0
            }

        self.strategy_stats[strategy_id]["pnl"] += round_trip_pnl
        pos_key = f"{symbol}_{side}"
        self.pos_pnl[pos_key] = self.pos_pnl.get(pos_key, 0.0) + round_trip_pnl

        if is_partial:
            return None

        total_trade_pnl = self.pos_pnl.pop(pos_key, 0.0)
        self.total_trades += 1
        self.strategy_stats[strategy_id]["total_trades"] += 1

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

        return total_trade_pnl

    def print_final_stats(self, elapsed: float):
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
