"""
1. Summary: Dedicated unit tests for the ExchangeSync state reconciliation subsystem.
2. Description: Validates synchronisation of open positions, closed positions detection with fallback pricing, missing TP1 trigger order auto-placement, and pending order tracking.
3. Context: Core financial correctness safeguard ensuring local and exchange states are perfectly synchronized.
"""
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import time
import pytest

from engine.reconciliation import ExchangeSync
from engine.positions import PositionLedger

class TestExchangeSync(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.ledger = PositionLedger()
        self.exchange = MagicMock()
        self.config = MagicMock()
        self.leverage_limits = {"BTCUSDT": 20}
        self.books = {}
        self.report_exit_calls = []

        def mock_report_exit(symbol, side, round_trip_pnl, exit_type="unknown"):
            self.report_exit_calls.append((symbol, side, round_trip_pnl, exit_type))
            self.ledger.remove_position(f"{symbol}_{side}")

        self.last_price = {"BTCUSDT": 50000.0}

        self.sync = ExchangeSync(
            exchange=self.exchange,
            ledger=self.ledger,
            config=self.config,
            leverage_limits=self.leverage_limits,
            books=self.books,
            report_exit_func=mock_report_exit,
            last_price=self.last_price
        )

    async def test_sync_new_open_position(self):
        # 1. Exchange reports an open position not in ledger
        self.exchange.get_positions = AsyncMock(return_value=[
            {
                "symbol": "BTCUSDT",
                "holdSide": "long",
                "total": "1.5",
                "averageOpenPrice": "50000.0",
                "leverage": "20"
            }
        ])
        self.exchange.get_open_orders = AsyncMock(return_value=[])

        await self.sync.sync_exchange_state()

        # Position should be added to ledger
        self.assertTrue(self.ledger.is_open("BTCUSDT_buy"))
        pos = self.ledger.get_position("BTCUSDT_buy")
        self.assertEqual(pos["qty"], 1.5)
        self.assertEqual(pos["entry"], 50000.0)
        self.assertEqual(pos["strategy_id"], "legacy_sync")

    async def test_sync_existing_position_update(self):
        # 1. Pre-populate position in ledger
        self.ledger.add_position("BTCUSDT_buy", {
            "side": "buy", "qty": 1.0, "entry": 49000.0,
            "orig_side": "buy", "is_contr": False,
            "margin": 2450.0, "ts": time.time(),
            "strategy_id": "test_strat"
        })

        # 2. Exchange reports updated details
        self.exchange.get_positions = AsyncMock(return_value=[
            {
                "symbol": "BTCUSDT",
                "holdSide": "long",
                "total": "1.2",
                "averageOpenPrice": "49500.0",
                "leverage": "20"
            }
        ])
        self.exchange.get_open_orders = AsyncMock(return_value=[])

        await self.sync.sync_exchange_state()

        # Ledger position must be updated
        pos = self.ledger.get_position("BTCUSDT_buy")
        self.assertEqual(pos["qty"], 1.2)
        self.assertEqual(pos["entry"], 49500.0)

    async def test_detect_disappeared_closed_position(self):
        # 1. Position exists locally but is gone on exchange (meaning it exited)
        self.ledger.add_position("BTCUSDT_buy", {
            "side": "buy", "qty": 1.0, "entry": 50000.0,
            "orig_side": "buy", "is_contr": False,
            "margin": 2500.0, "ts": time.time(),
            "strategy_id": "test_strat",
            "tp_price": 51000.0,
            "stop_price": 49000.0
        })

        self.exchange.get_positions = AsyncMock(return_value=[])
        self.exchange.get_open_orders = AsyncMock(return_value=[])
        # Fail history queries to trigger local math calculation
        self.exchange.get_history_positions = AsyncMock(side_effect=Exception("API Error"))
        self.exchange.get_fills = AsyncMock(side_effect=Exception("API Error"))

        # Setup current price close to TP target
        self.last_price["BTCUSDT"] = 50999.0

        await self.sync.sync_exchange_state()

        # Position should be closed out locally and exit reported
        self.assertFalse(self.ledger.is_open("BTCUSDT_buy"))
        self.assertEqual(len(self.report_exit_calls), 1)
        reported = self.report_exit_calls[0]
        self.assertEqual(reported[0], "BTCUSDT")
        self.assertEqual(reported[1], "buy")
        self.assertEqual(reported[3], "tp") # exit type should resolve to TP because price is closer to TP

    async def test_reconcile_missing_tp1_order(self):
        # 1. Position is open and has a tp1 target, but no open plan orders on-exchange
        self.ledger.add_position("BTCUSDT_buy", {
            "side": "buy", "qty": 1.0, "entry": 50000.0,
            "orig_side": "buy", "is_contr": False,
            "margin": 2500.0, "ts": time.time(),
            "strategy_id": "test_strat",
            "tp1_price": 50500.0,
            "tp1_qty": 0.5
        })

        self.exchange.get_positions = AsyncMock(return_value=[
            {
                "symbol": "BTCUSDT",
                "holdSide": "long",
                "total": "1.0",
                "averageOpenPrice": "50000.0",
                "leverage": "20"
            }
        ])
        self.exchange.get_open_orders = AsyncMock(return_value=[])

        # Exchange says no open plan orders
        self.exchange.get_open_tpsl_orders = AsyncMock(return_value=[])
        self.exchange.place_tpsl_order = AsyncMock(return_value={"code": "00000"})

        await self.sync.sync_exchange_state()

        # It should automatically place the missing TP1 plan order
        self.exchange.place_tpsl_order.assert_called_once_with(
            symbol="BTCUSDT",
            plan_type="profit",
            trigger_price=50500.0,
            qty=0.5,
            hold_side="long"
        )

    async def test_sync_pending_and_clear_stale_orders(self):
        # 1. Sane pending order syncing
        self.exchange.get_positions = AsyncMock(return_value=[])
        self.exchange.get_open_orders = AsyncMock(return_value=[
            {
                "symbol": "BTCUSDT",
                "side": "buy",
                "orderId": "order_789"
            }
        ])

        # Pre-populate stale pending entry
        self.ledger.add_pending("ETHUSDT_buy")

        await self.sync.sync_exchange_state()

        # New pending order must be added
        self.assertTrue(self.ledger.is_pending("BTCUSDT_buy"))
        # Stale pending entry must be cleared
        self.assertFalse(self.ledger.is_pending("ETHUSDT_buy"))

if __name__ == "__main__":
    unittest.main()
