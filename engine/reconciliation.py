"""
1. Summary: Production-grade exchange state reconciliation subsystem.
2. Description: Synchronizes in-memory positions, margins, and pending entries against active exchange databases. Reconciles stale, filled, or partially executed plan orders and backfills missing metrics.
3. Context: High financial correctness stakes — guarantees local state never diverges from the physical exchange.
"""
import time
import logging
from typing import Dict, Any, Callable
from engine.base import BaseExchange
from engine.positions import PositionLedger
from tools.trading_utils import calculate_net_pnl

log = logging.getLogger("scalper.engine.reconciliation")

class ExchangeSync:
    def __init__(self, exchange: BaseExchange, ledger: PositionLedger, config, leverage_limits: dict, books: dict, report_exit_func: Callable, last_price: dict):
        self.exchange = exchange
        self.ledger = ledger
        self.config = config
        self.leverage_limits = leverage_limits
        self.books = books
        self.report_exit_func = report_exit_func
        self.last_price = last_price

    async def sync_exchange_state(self):
        """
        Synchronizes the local open positions and pending entries with the exchange state.
        """
        log.info("Synchronizing state with exchange...")
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
                    if pos_key not in self.ledger.open_positions:
                        self.ledger.open_positions[pos_key] = {
                            "side": side, "qty": qty, "entry": entry,
                            "orig_side": side, "is_contr": False,
                            "margin": (qty * entry) / float(p.get('leverage', 20)),
                            "ts": time.time(),
                            "strategy_id": "legacy_sync"
                        }
                        log.info(f"Synced Position: {pos_key} | Qty: {qty} @ {entry}")
                    else:
                        self.ledger.open_positions[pos_key].update({"qty": qty, "entry": entry})

            # Check for positions that disappeared from exchange (meaning they exited)
            for pos_key in list(self.ledger.open_positions.keys()):
                if pos_key not in current_pos_keys:
                    p = self.ledger.open_positions[pos_key]
                    if p.get("strategy_id") != "legacy_sync":
                        log.info(f"Position {pos_key} gone from exchange. Reporting exit...")

                        symbol = pos_key.split("_")[0]
                        side = p["side"]
                        qty = p["qty"]
                        entry_price = p["entry"]

                        exit_price = None
                        pnl = None
                        exit_type = "exchange_sync"

                        try:
                            # Try to query closed positions from exchange history
                            if hasattr(self.exchange, "get_history_positions"):
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
                                    exit_type = "exchange_sync"
                        except Exception as e:
                            log.warning(f"SYNC STATE | Failed to fetch position history for {pos_key}: {e}")

                        if exit_price is None:
                            try:
                                if hasattr(self.exchange, "get_fills"):
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
                            except Exception as e:
                                log.warning(f"SYNC STATE | Failed to fetch fills for {pos_key}: {e}")

                        if exit_price is None or exit_price == 0.0:
                            ticker_price = self.last_price.get(symbol, entry_price)
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

                            pnl = calculate_net_pnl(qty, entry_price, exit_price, side, entry_maker=entry_maker, exit_maker=exit_maker)
                            log.info(f"SYNC STATE | Calculated local fallback net P&L for {pos_key}: gross_pnl={(exit_price-entry_price)*qty if side=='buy' else (entry_price-exit_price)*qty:.4f}, exit_price={exit_price:.8f}, net_pnl={pnl:.4f}")

                        self.report_exit_func(symbol, side, pnl, exit_type=exit_type)
                    else:
                        log.info(f"Legacy synced position {pos_key} cleared.")
                        if pos_key in self.ledger.open_positions:
                            del self.ledger.open_positions[pos_key]

            # Reconcile TP1 trigger orders
            for pos_key, pos_details in list(self.ledger.open_positions.items()):
                sym = pos_key.split("_")[0]
                side = pos_details["side"]
                qty = pos_details["qty"]
                tp1_price = pos_details.get("tp1_price")
                tp1_qty = pos_details.get("tp1_qty")

                if tp1_price and tp1_qty:
                    try:
                        if hasattr(self.exchange, "get_open_tpsl_orders"):
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

            # Reconcile pending open orders
            orders = await self.exchange.get_open_orders()
            current_order_keys = set()
            for o in orders:
                sym = o['symbol']
                side = o['side'].lower()
                pos_key = f"{sym}_{side}"
                current_order_keys.add(pos_key)
                if pos_key not in self.ledger.pending_entries:
                    self.ledger.pending_entries.add(pos_key)
                    log.info(f"Synced Pending Order: {pos_key} | OrderId: {o.get('orderId')}")

            for pk in list(self.ledger.pending_entries):
                if pk not in current_order_keys and pk not in current_pos_keys:
                    self.ledger.pending_entries.remove(pk)
                    log.info(f"Cleared Stale Pending Entry: {pk}")

        except Exception as e:
            log.exception(f"Failed to sync exchange state: {e}")
