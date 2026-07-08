import logging
from typing import Dict, Any, Optional
from engine.base import BaseExchange, BaseStrategy
from engine.exchanges.bitget import BitgetExchange
from config import MODE, BITGET_API_KEY, BITGET_SECRET_KEY, BITGET_PASSPHRASE, BITGET_API_KEY_DEMO, BITGET_SECRET_KEY_DEMO, BITGET_PASSPHRASE_DEMO

log = logging.getLogger("engine.router")

class SignalRouter:
    def __init__(self, mode: str = MODE, exchange: Optional[BaseExchange] = None):
        self.mode = mode
        self.exchange = exchange
        if not self.exchange:
            self._init_exchange()

    def _init_exchange(self):
        if self.mode == "paper":
            from engine.simulation import SimulationEngine
            self.exchange = SimulationEngine()
        elif self.mode == "demo":
            self.exchange = BitgetExchange(BITGET_API_KEY_DEMO, BITGET_SECRET_KEY_DEMO, BITGET_PASSPHRASE_DEMO, is_demo=True)
        elif self.mode == "live":
            self.exchange = BitgetExchange(BITGET_API_KEY, BITGET_SECRET_KEY, BITGET_PASSPHRASE, is_demo=False)
        else:
            raise ValueError(f"Unknown mode: {self.mode}")

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
            return await self.exchange.place_order(symbol, side, "limit", qty, price, **signal)
