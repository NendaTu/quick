import logging
import asyncio
import time
from typing import Dict, List, Optional, Any
from simulator import Simulator
from engine.base import BaseExchange

log = logging.getLogger("engine.simulation")

class SimulationEngine(BaseExchange, Simulator):
    """
    The Unified Simulation Engine.
    Inherits from Simulator to reuse its battle-tested simulation logic,
    but implements the BaseExchange interface for the new router.
    """
    def __init__(self, use_db=True):
        Simulator.__init__(self, use_db=use_db)
        self.mode = "paper"

    async def get_tickers(self) -> List[Dict]:
        # Implementation from BitGetClient proxy or local state
        return await self.client.get_tickers()

    async def get_symbols(self) -> List[Dict]:
        return await self.client.get_symbols()

    async def get_candles(self, symbol: str, timeframe: str, limit: int = 100) -> List[List]:
        # Try local cache first, then Bitget API via client
        return await self.client.get_candles(symbol, timeframe, limit)

    async def place_order(self, symbol: str, side: str, order_type: str, qty: float, price: Optional[float] = None, **kwargs) -> Dict:
        """
        Adapts the BaseExchange.place_order call to Simulator's place_trade_oco
        or other internal simulation methods.
        """
        # If it's a standard entry with SL/TP, use OCO
        if "stop_price" in kwargs and "exit_price" in kwargs:
            return self.place_trade_oco(
                symbol, side, qty,
                price or kwargs.get("entry_price"),
                kwargs["stop_price"],
                kwargs["exit_price"],
                **kwargs
            )

        # Simple Market/Limit order
        if order_type == "market":
            self._execute_entry_direct(symbol, side, qty, self.last_price.get(symbol, 0), "market_simple")
            return {"code": "00000", "data": {"orderId": "sim_market_123"}}

        log.warning(f"SimEngine: Order {order_type} {side} {qty} {symbol} not fully implemented yet")
        return {"code": "00000", "data": {"orderId": "sim_simple_123"}}

    async def scale_position(self, symbol: str, side: str, qty: float, **kwargs) -> Dict:
        """
        Adds to an existing position.
        """
        price = self.last_price.get(symbol, 0)
        self._execute_entry_direct(symbol, side, qty, price, "scale_up")
        return {"code": "00000", "data": {"orderId": f"scale_{int(time.time())}"}}

    async def get_trading_equity(self) -> float:
        return self.equity

    async def get_positions(self) -> List[Dict]:
        # Convert internal simulator positions to Bitget-like dicts
        res = []
        for (sym, side), p in self.positions.items():
            res.append({
                'symbol': sym,
                'holdSide': 'long' if side == 'buy' else 'short',
                'total': str(p['qty']),
                'averageOpenPrice': str(p['entry_price']),
                'leverage': str(self.leverage_limits.get(sym, 20))
            })
        return res

    async def get_open_orders(self) -> List[Dict]:
        res = []
        for o in self.pending_orders:
            res.append({
                'symbol': o['symbol'],
                'side': o['pos_side'],
                'orderId': str(o.get('id', '0')),
                'price': str(o.get('price', 0))
            })
        return res

    async def cancel_order(self, symbol: str, order_id: str) -> Dict:
        self.pending_orders = [o for o in self.pending_orders if str(o.get('id')) != str(order_id)]
        return {"code": "00000", "msg": "success"}

    async def get_order_status(self, symbol: str, order_id: str) -> Dict:
        # Mocking status as filled if not in pending
        found = any(str(o.get('id')) == str(order_id) for o in self.pending_orders)
        return {"orderId": order_id, "status": "live" if found else "filled"}

    # Additional methods to support backtesting loop directly will be added here
    # in Step 4 of the plan.
