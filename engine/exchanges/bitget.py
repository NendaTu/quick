import logging
from typing import Dict, List, Optional
from engine.base import BaseExchange
from bitget_client import BitGetClient, BitGetWSClient

log = logging.getLogger("engine.exchanges.bitget")

class BitgetExchange(BaseExchange):
    def __init__(self, api_key: str, secret_key: str, passphrase: str):
        self.client = BitGetClient(api_key, secret_key, passphrase)
        self.ws_client: Optional[BitGetWSClient] = None

    async def get_tickers(self) -> List[Dict]:
        return await self.client.get_tickers()

    async def get_symbols(self) -> List[Dict]:
        return await self.client.get_symbols()

    async def get_candles(self, symbol: str, timeframe: str, limit: int = 100) -> List[List]:
        return await self.client.get_candles(symbol, timeframe, limit)

    async def place_order(self, symbol: str, side: str, order_type: str, qty: float, price: Optional[float] = None, **kwargs) -> Dict:
        # Implementation for Bitget order placement (REST API)
        # This will be used for Live and Demo modes
        params = {
            "symbol": symbol,
            "side": side,
            "orderType": order_type,
            "size": str(qty),
        }
        if price:
            params["price"] = str(price)

        # Add any extra params (e.g., productType for Bitget V2)
        params.update(kwargs)

        log.info(f"Bitget: Placing {order_type} {side} order for {qty} {symbol} @ {price}")
        return {"code": "00000", "msg": "Order placement simulated in foundation", "data": {"orderId": "sim_123"}}

    async def scale_position(self, symbol: str, side: str, qty: float, **kwargs) -> Dict:
        # For Bitget, scaling up is just another order in the same direction
        return await self.place_order(symbol, side, "market", qty, **kwargs)

    async def close(self):
        await self.client.close()
        if self.ws_client:
            self.ws_client.stop()
