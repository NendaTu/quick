"""
Console Publisher Module for Uniform Application Outputs

Ensures all application outputs, heartbeats, placements, fills, and exits are
formatted in a structured, consistent, and beautiful layout across all engines,
timeframes, and strategies.
"""

import logging
from datetime import datetime
import pytz

log = logging.getLogger("scalper.publisher")

class ConsolePublisher:
    """
    Independent console publisher that formats and prints standard outputs,
    heartbeats, entries, exits, and performance tables uniformly.
    """
    @staticmethod
    def publish_heartbeat(virtual_time_s: float, equity: float, trades: int, win_rate: float, profit_ratio: float, open_positions_count: int, signals_fired: int = 0):
        dt_str = datetime.fromtimestamp(virtual_time_s, tz=pytz.UTC).strftime("%Y-%m-%d %H:%M:%S")
        pr_str = f"{profit_ratio:.2f}" if profit_ratio != float('inf') else "inf"
        msg = f"HEARTBEAT | Virtual Time: {dt_str} | Equity: {equity:.2f} | Trades: {trades} | Win%: {win_rate:.1f}% | PR: {pr_str} | Open: {open_positions_count} | Signals Fired: {signals_fired}"
        log.info(msg)

    @staticmethod
    def publish_order_placement(symbol: str, side: str, qty: float, price: float, margin_reserved: float, order_type: str = "LIMIT"):
        msg = f"PLACED {order_type.upper()} ENTRY {symbol} {side.upper()} {qty:.3f} @ {price:.8f} | Margin Reserved: {margin_reserved:.2f}"
        log.info(msg)

    @staticmethod
    def publish_order_fill(symbol: str, side: str, strategy_id: str, qty: float, price: float, order_type: str, drt: float, equity: float, used_margin: float, btc_conf: str = ""):
        msg = f"FILLED ENTRY {symbol} {side.upper()} [Strat: {strategy_id}] {qty:.3f} @ {price:.8f} ({order_type.upper()}) [{btc_conf}] drt={drt:.4f} | equity={equity:.2f} used_margin={used_margin:.2f}"
        log.info(msg)

    @staticmethod
    def publish_exit(symbol: str, side: str, strategy_id: str, is_partial: bool, exit_type: str, order_type: str, price: float, pnl: float, net_pnl: float, entry_drt: float, exit_drt: float, equity: float, used_margin: float, btc_conf: str = ""):
        exit_str = "PARTIAL" if is_partial else "FULL"
        msg = f"EXIT {exit_str} {symbol} {side.upper()} [Strat: {strategy_id}] {exit_type.upper()} ({order_type.upper()}) @ {price:.8f} PnL={pnl:.4f} net={net_pnl:.4f} [{btc_conf}] drt_entry={entry_drt:.4f} drt_exit={exit_drt:.4f} | equity={equity:.2f} used_margin={used_margin:.2f}"
        log.info(msg)
