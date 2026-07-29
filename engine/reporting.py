"""
1. Summary: Specialized stats tracking and performance reporting subsystem.
2. Description: Aggregates real-time trade results, win rates, drawdowns, gross profits, and compounding curves. Dispatches formatted console logs summarizing performance metrics by asset and strategy.
3. Context: Injected into the core loops to capture execution results statelessly and finalize runs with detailed audits.
"""
import time
import logging
from typing import Dict, List, Any

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
