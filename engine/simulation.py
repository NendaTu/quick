import logging
import asyncio
import time
from typing import Dict, List, Optional, Any
import config
from simulator import Simulator
from engine.base import BaseExchange
from bitget_client import BitGetWSClient

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
        res = await self.client.get_candles(symbol, timeframe, limit)
        # [REPAIR-20260708] Backpacking: Save fetched candles to DB
        if self.db and isinstance(res, list):
            for c in res:
                ts = float(c[0]) / 1000
                o, h, l, cl, v = map(float, c[1:6])
                self.db.save_candle(symbol, timeframe, ts, o, h, l, cl, v)
        return res

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

    async def data_feed_task(self, engine, external_feed=None):
        """
        Unified Paper feed task: links Simulator logic to Engine state.
        """
        self.engine = engine # Ensure Simulator has reference to Engine

        if external_feed is None:
            # Paper mode usually needs a real-time feed if running in main.py
            symbols = list(set(self.discovered_assets + [config.BTC_SYMBOL]))
            ws_client = BitGetWSClient(symbols, self._ws_callback)
            asyncio.create_task(ws_client.run())
        else:
            asyncio.create_task(self._external_feed_loop(external_feed))

        last_heartbeat = time.time()
        while True:
            try:
                # 1. Simulator maintains self.equity based on trade fills.
                # Engine needs to know this value.
                engine.equity = self.equity

                # 2. Simulator logic: process pending orders (TP/SL/Limits)
                await self._process_orders()

                # 3. Heartbeat
                now = time.time()
                if now - last_heartbeat > 60:
                    log.debug("SimulationEngine heartbeat")
                    last_heartbeat = now

                if engine.stop_event.is_set():
                    break

                await asyncio.sleep(0.1)
            except Exception as e:
                log.error(f"SimulationEngine loop error: {e}")
                await asyncio.sleep(1)
