import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import time
import sys
import os

# Adjust path to import codebase modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from engine.core import Engine
from engine.exchanges.bitget import BitgetExchange

class TestReconciliation(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Prevent starting websocket clients during test initialization
        self.ws_patcher = patch("engine.exchanges.bitget.BitGetWSClient")
        self.mock_ws = self.ws_patcher.start()

        # Patch sync_time to avoid network requests
        self.sync_time_patcher = patch("bitget_client.BitGetClient.sync_time", new_callable=AsyncMock)
        self.mock_sync_time = self.sync_time_patcher.start()

    async def asyncTearDown(self):
        self.ws_patcher.stop()
        self.sync_time_patcher.stop()

    @patch("engine.exchanges.bitget.BitGetClient.place_order", new_callable=AsyncMock)
    async def test_place_order_registers_limit_in_pending_orders(self, mock_place_order):
        # Mock successful order response from Bitget API
        mock_place_order.return_value = {
            "code": "00000",
            "msg": "success",
            "data": {
                "orderId": "mock_order_999",
                "clientOid": "mock_client_999"
            }
        }

        # Initialize BitgetExchange
        exchange = BitgetExchange(
            api_key="mock_key",
            secret_key="mock_secret",
            passphrase="mock_passphrase",
            is_demo=True
        )

        # Mock Engine link
        exchange.engine = MagicMock()
        exchange.engine.leverage_limits = {"BTCUSDT": 50}

        # Mock leverage and margin mode calls to prevent network activity
        exchange.set_margin_mode = AsyncMock(return_value={"code": "00000"})
        exchange.set_leverage = AsyncMock(return_value={"code": "00000"})

        # Place a limit entry order
        res = await exchange.place_order(
            symbol="BTCUSDT",
            side="buy",
            order_type="limit",
            qty=0.01,
            price=60000.0,
            stop_price=59000.0,
            tp_price=62000.0
        )

        self.assertEqual(res["code"], "00000")

        # Verify it was registered in exchange.pending_orders
        self.assertEqual(len(exchange.pending_orders), 1)
        o = exchange.pending_orders[0]
        self.assertEqual(o["symbol"], "BTCUSDT")
        self.assertEqual(o["pos_side"], "buy")
        self.assertEqual(o["type"], "entry_limit")
        self.assertEqual(o["price"], 60000.0)
        self.assertEqual(o["qty"], 0.01)
        self.assertEqual(o["orderId"], "mock_order_999")
        self.assertEqual(o["stop_price"], 59000.0)
        self.assertEqual(o["tp_price"], 62000.0)

        await exchange.close()

    @patch("engine.exchanges.bitget.BitGetClient.get_positions", new_callable=AsyncMock)
    @patch("engine.exchanges.bitget.BitGetClient.get_open_orders", new_callable=AsyncMock)
    @patch("engine.exchanges.bitget.BitGetClient.get_history_positions", new_callable=AsyncMock)
    @patch("engine.exchanges.bitget.BitGetClient.get_fills", new_callable=AsyncMock)
    async def test_reconciliation_gone_position_pnl_with_history(self, mock_get_fills, mock_get_history, mock_get_open_orders, mock_get_positions):
        # 1. Initialize Engine in demo mode
        engine = Engine(use_db=False, mode="demo")

        # Setup mocks
        mock_get_positions.return_value = [] # no open positions
        mock_get_open_orders.return_value = [] # no pending orders

        # Mock position history returned from exchange
        mock_get_history.return_value = [
            {
                "symbol": "BTCUSDT",
                "holdSide": "long",
                "openPrice": "60000",
                "closePrice": "61000",
                "realizedPL": "10.0",
                "fee": "0.1"
            }
        ]

        # Populate open_positions with a position that is about to disappear
        engine.open_positions["BTCUSDT_buy"] = {
            "side": "buy",
            "qty": 0.01,
            "entry": 60000.0,
            "margin": 12.0,
            "ts": time.time() - 100,
            "strategy_id": "test_strat"
        }

        # Run state synchronization (which should detect position is gone and fetch history)
        await engine._sync_exchange_state()

        # Check if the position was removed and reported correctly
        self.assertNotIn("BTCUSDT_buy", engine.open_positions)

        # Check reported exit details
        self.assertEqual(engine.total_trades, 1)
        self.assertEqual(engine.winning_trades, 1)
        self.assertGreater(engine.cumulative_pnl, 0.0)

        await engine.exchange.close()

    @patch("engine.exchanges.bitget.BitGetClient.get_positions", new_callable=AsyncMock)
    @patch("engine.exchanges.bitget.BitGetClient.get_open_orders", new_callable=AsyncMock)
    @patch("engine.exchanges.bitget.BitGetClient.get_history_positions", new_callable=AsyncMock)
    @patch("engine.exchanges.bitget.BitGetClient.get_fills", new_callable=AsyncMock)
    async def test_reconciliation_gone_position_pnl_with_fallback(self, mock_get_fills, mock_get_history, mock_get_open_orders, mock_get_positions):
        # Initialize Engine in demo mode
        engine = Engine(use_db=False, mode="demo")

        # Setup mocks
        mock_get_positions.return_value = [] # no open positions
        mock_get_open_orders.return_value = [] # no pending orders

        # Fail the history and fills queries to triggerfallback
        mock_get_history.side_effect = Exception("API Timeout")
        mock_get_fills.side_effect = Exception("API Timeout")

        # Setup an open position with targets stored
        engine.open_positions["BTCUSDT_buy"] = {
            "side": "buy",
            "qty": 0.01,
            "entry": 60000.0,
            "margin": 12.0,
            "ts": time.time() - 100,
            "strategy_id": "test_strat",
            "stop_price": 59000.0,
            "tp_price": 62000.0
        }

        # Let's say ticker has moved closer to stop loss (59100.0)
        engine.exchange.last_price["BTCUSDT"] = 59100.0

        # Run state synchronization (which should trigger local fallback SL calculation)
        await engine._sync_exchange_state()

        # Check reported exit details
        self.assertNotIn("BTCUSDT_buy", engine.open_positions)
        self.assertEqual(engine.total_trades, 1)
        self.assertEqual(engine.losing_trades, 1)
        self.assertLess(engine.cumulative_pnl, 0.0)

        await engine.exchange.close()

if __name__ == "__main__":
    unittest.main()
