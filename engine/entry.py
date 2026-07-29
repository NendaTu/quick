"""
1. Summary: Unified Signal Router executing orders across paper and live exchange interfaces.
2. Description: Parses standardized signal dictionaries emitted by strategies and directs execution handlers. Maps simulated OCO limit targets to the paper engine and maps live limit orders to REST API endpoints.
3. Context: Instantiated by Engine. Relies on BitgetExchange and SimulationEngine wrappers to place trades.
"""
import logging
from typing import Dict, Any, Optional
from engine.base import BaseExchange, BaseStrategy
from engine.exchanges.bitget import BitgetExchange
from config import MODE, BITGET_API_KEY, BITGET_SECRET_KEY, BITGET_PASSPHRASE, BITGET_API_KEY_DEMO, BITGET_SECRET_KEY_DEMO, BITGET_PASSPHRASE_DEMO

log = logging.getLogger("engine.router")

class SignalRouter:
    def __init__(self, mode: str, exchange: BaseExchange):
        # P1-5: Require pre-constructed exchange, removing dead/duplicate _init_exchange selection path
        self.mode = mode.lower().strip(' "').strip("'")
        self.exchange = exchange

    async def route_signal(self, signal: Dict[str, Any]):
        """
        Routes an entry/exit signal to the appropriate exchange/simulation handler.
        """
        symbol = signal["symbol"]
        side = signal["side"]
        qty = signal["qty"]
        price = signal.get("entry_price") or signal.get("price")

        log.info(f"ROUTER [{self.mode.upper()}]: Routing {side} for {symbol} - {qty} @ {price}")

        # In a real implementation, this would call self.exchange.place_order
        # For simulation, it might call place_trade_oco
        if self.mode == "paper":
            # Special handling for simulation OCO
            # Remove keys that are passed as positional arguments
            kwargs = signal.copy()
            for key in ["side", "qty", "entry_price", "stop_price", "exit_price"]:
                kwargs.pop(key, None)

            res = self.exchange.place_trade_oco(
                symbol, side, qty,
                signal["entry_price"],
                signal["stop_price"],
                signal["exit_price"],
                **kwargs
            )
            # Ensure return is awaitable if needed, though for now Engine just awaits route_signal
            return res
        else:
            # Live/Demo exchange calls are usually async
            # Explicitly filter out keys that are passed as positional arguments
            kwargs = signal.copy()
            for key in ["symbol", "side", "qty", "price", "entry_price"]:
                kwargs.pop(key, None)

            # P0-5: Dynamically read ENTRY_ORDER_TYPE from config context
            order_type = "limit"
            if self.exchange and hasattr(self.exchange, "config"):
                order_type = getattr(self.exchange.config, "ENTRY_ORDER_TYPE", "limit")
            else:
                import config as global_config
                order_type = getattr(global_config, "ENTRY_ORDER_TYPE", "limit")

            return await self.exchange.place_order(symbol, side, order_type, qty, price, **kwargs)
