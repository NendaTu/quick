import logging, asyncio
from typing import Dict, List, Optional
from engine.base import BaseExchange
from bitget_client import BitGetClient, BitGetWSClient

log = logging.getLogger("engine.exchanges.bitget")

from simulator import Simulator
import config

class BitgetExchange(Simulator, BaseExchange):
    # [TECH-001] Optimized Acquisition Defaults
    # Targeting a zero-429 baseline for long historical runs.
    DEFAULT_RPS = 10
    DEFAULT_CONCURRENCY = 5

    def __init__(self, api_key: str, secret_key: str, passphrase: str, is_demo: bool = False):
        # Dual-Client Architecture:
        # 1. data_client: Always uses Live keys for market data to ensure availability and fix 40099.
        self.data_client = BitGetClient(config.BITGET_API_KEY, config.BITGET_SECRET_KEY, config.BITGET_PASSPHRASE, is_demo=False)

        # 2. execution_client: Handles private actions (orders, balance) in Live or Demo environment.
        self.client_exec = BitGetClient(api_key, secret_key, passphrase, is_demo=is_demo)

        # Initialize Simulator first with the data client to get OHLCV/TA capabilities
        # This ensures Simulator.warm_up uses the correct keys and environment.
        Simulator.__init__(self, use_db=True, client=self.data_client)

        self.ws_client: Optional[BitGetWSClient] = None
        self.is_demo = is_demo
        self.engine = None

        # Symbol mapping for Demo Mode (Canonical <-> Exchange)
        self.symbol_map = {} # canonical -> exchange
        self.rev_symbol_map = {} # exchange -> canonical

    def _normalize_symbol(self, symbol: str) -> str:
        """Maps an exchange-specific symbol (like SBTCUSDT) to its canonical form (BTCUSDT)."""
        return self.rev_symbol_map.get(symbol, symbol)

    def _denormalize_symbol(self, symbol: str) -> str:
        """Maps a canonical symbol (like BTCUSDT) to its exchange-specific form (SBTCUSDT)."""
        return self.symbol_map.get(symbol, symbol)

    async def get_tickers(self) -> List[Dict]:
        return await self.data_client.get_tickers()

    async def get_symbols(self) -> List[Dict]:
        return await self.data_client.get_symbols()

    async def get_candles(self, symbol: str, timeframe: str, limit: int = 100) -> List[List]:
        return await self.data_client.get_candles(symbol, timeframe, limit)

    async def place_order(self, symbol: str, side: str, order_type: str, qty: float, price: Optional[float] = None, **kwargs) -> Dict:
        """
        Implementation for Bitget V2 order placement.
        Supports embedded SL and TP via presetStopLossPrice and presetTakeProfitPrice.
        """
        # Map canonical symbol to exchange symbol for Demo mode
        exch_symbol = self._denormalize_symbol(symbol)

        tp_price = kwargs.get("exit_price") or kwargs.get("tp_price") or kwargs.get("presetTakeProfitPrice")
        sl_price = kwargs.get("stop_price") or kwargs.get("sl_price") or kwargs.get("presetStopLossPrice")

        # Filter out keys already handled or not needed by API
        filtered_kwargs = kwargs.copy()
        for key in ["exit_price", "tp_price", "stop_price", "sl_price", "features", "strategy_id"]:
            filtered_kwargs.pop(key, None)

        log.info(f"Bitget: Placing {order_type} {side} order for {qty} {exch_symbol} @ {price} (TP: {tp_price}, SL: {sl_price})")

        res = await self.client_exec.place_order(
            symbol=exch_symbol,
            side=side,
            order_type=order_type,
            qty=qty,
            price=price,
            tp_price=tp_price,
            sl_price=sl_price,
            **filtered_kwargs
        )
        log.info(f"Bitget Order Result: {res}")
        return res

    async def get_balance(self) -> Optional[float]:
        """
        Fetches the actual USDT balance from the exchange.
        """
        accounts = await self.client_exec.get_account_balance()
        if not accounts: return None
        for acc in accounts:
            if acc.get("marginCoin") == "USDT":
                return float(acc.get("available", 0))
        return 0.0

    async def get_trading_equity(self) -> float:
        """
        Returns equity for sizing, either virtual or real depending on config.
        """
        if config.USE_VIRTUAL_BALANCE:
            return self.equity # Inherited from Simulator

        real = await self.get_balance()
        return real if real is not None else self.equity

    async def scale_position(self, symbol: str, side: str, qty: float, **kwargs) -> Dict:
        # For Bitget, scaling up is just another order in the same direction
        return await self.place_order(symbol, side, "market", qty, **kwargs)

    async def data_feed_task(self, engine, external_feed=None):
        """
        Connects to Bitget WebSocket for real-time updates.
        """
        if not self.ws_client:
            # Subscribe to exchange-specific symbols (denormalized)
            symbols = [self._denormalize_symbol(s) for s in engine.enabled_assets + [config.BTC_SYMBOL]]
            self.ws_client = BitGetWSClient(symbols, self._ws_callback)
            asyncio.create_task(self.ws_client.run())

    async def _ws_callback(self, msg):
        """
        Handles incoming WebSocket messages and updates the engine's order books.
        """
        if "data" not in msg:
            return

        data = msg["data"]
        arg = msg.get("arg", {})
        symbol = arg.get("instId")
        channel = arg.get("channel")

        if not symbol:
            return

        norm_sym = self._normalize_symbol(symbol)

        from orderbook import OrderBook
        if norm_sym not in self.engine.books:
            self.engine.books[norm_sym] = OrderBook(norm_sym)

        book = self.engine.books[norm_sym]

        if channel == "books15":
            # Update canonical simulator state via normalized symbol
            if norm_sym in self.books:
                 self.books[norm_sym].bids = [(float(p), float(q)) for p, q in data[0].get("bids", [])]
                 self.books[norm_sym].asks = [(float(p), float(q)) for p, q in data[0].get("asks", [])]
                 self.books[norm_sym].mid_price = (self.books[norm_sym].best_bid + self.books[norm_sym].best_ask) / 2

            for d in data:
                book.update(d.get("bids", []), d.get("asks", []), ts=int(d.get("ts", 0))/1000)
        elif channel == "trade":
            # For now we just use orderbook for mid price,
            # but we could track trades if needed.
            pass

    async def close(self):
        # Simulator (parent) might have its own close or needs its client closed
        if hasattr(self, "data_client"):
            await self.data_client.close()
        if hasattr(self, "client_exec"):
            await self.client_exec.close()
        if self.ws_client:
            self.ws_client.stop()
