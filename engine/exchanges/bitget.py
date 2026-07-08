import logging, asyncio, time
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
        self.ws_private: Optional[BitGetWSClient] = None
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
        if not accounts or not isinstance(accounts, list):
            return None
        for acc in accounts:
            if isinstance(acc, dict) and acc.get("marginCoin") == "USDT":
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

    async def cancel_order(self, symbol: str, order_id: str) -> Dict:
        exch_symbol = self._denormalize_symbol(symbol)
        return await self.client_exec.cancel_order(exch_symbol, order_id)

    async def get_order_status(self, symbol: str, order_id: str) -> Dict:
        exch_symbol = self._denormalize_symbol(symbol)
        return await self.client_exec.get_order_status(exch_symbol, order_id)

    async def get_positions(self) -> List[Dict]:
        raw_positions = await self.client_exec.get_positions()
        if not isinstance(raw_positions, list):
            return []
        # Map back to canonical symbols
        valid_positions = []
        for p in raw_positions:
            if isinstance(p, dict):
                p['symbol'] = self._normalize_symbol(p.get('symbol', ''))
                valid_positions.append(p)
        return valid_positions

    async def get_open_orders(self) -> List[Dict]:
        raw_orders = await self.client_exec.get_open_orders()
        if not isinstance(raw_orders, list):
            return []
        valid_orders = []
        for o in raw_orders:
            if isinstance(o, dict):
                o['symbol'] = self._normalize_symbol(o.get('symbol', ''))
                valid_orders.append(o)
        return valid_orders

    async def data_feed_task(self, engine, external_feed=None):
        """
        Connects to Bitget WebSocket for real-time updates and manages exchange background tasks.
        """
        if not self.ws_client:
            # 1. Public Data Feed
            symbols = [self._denormalize_symbol(s) for s in engine.enabled_assets + [config.BTC_SYMBOL]]
            self.ws_client = BitGetWSClient(symbols, self._ws_callback)
            asyncio.create_task(self.ws_client.run())

            # 2. Private Execution Feed (Fills, Status)
            if not self.ws_private:
                self.ws_private = BitGetWSClient(
                    [], self._ws_private_callback, is_private=True,
                    api_key=self.client_exec.api_key,
                    secret_key=self.client_exec.secret_key,
                    passphrase=self.client_exec.passphrase
                )
                asyncio.create_task(self.ws_private.run())

            # 3. Safety Poller (REST reconciliation)
            asyncio.create_task(self._safety_poller(engine))

        # 4. Background Maintenance & Processing Loop
        last_heartbeat = time.time()
        while True:
            try:
                # Synchronize Simulator's virtual equity with Engine's tracked equity
                # (Engine._equity_monitor handles the reverse: polling exchange for real balance)
                self.equity = engine.equity

                # Process timeouts and chase logic
                await self._process_orders()

                # Heartbeat log
                now = time.time()
                if now - last_heartbeat > 60:
                    log.debug("BitgetExchange background loop heartbeat")
                    last_heartbeat = now

                if engine.stop_event.is_set():
                    break

                await asyncio.sleep(0.5)
            except Exception as e:
                log.error(f"BitgetExchange background loop error: {e}")
                await asyncio.sleep(5)

    async def _ws_private_callback(self, msg):
        """
        Handles private execution updates (fills, position changes).
        """
        if "data" not in msg: return
        data = msg["data"]
        arg = msg.get("arg", {})
        channel = arg.get("channel")

        if channel == "orders":
            for o in data:
                status = o.get("status")
                order_id = o.get("orderId")
                symbol = self._normalize_symbol(o.get("instId"))
                log.info(f"PRIVATE EVENT | Order {order_id} ({symbol}) status: {status}")
                # Fills and cancellations are primary triggers for engine reconciliation
                if status in ["filled", "cancelled", "partially_filled"]:
                    await self.engine._sync_exchange_state()

        elif channel == "positions":
            # Position changes trigger a full sync to ensure Engine and Exchange are aligned
            await self.engine._sync_exchange_state()

        elif channel == "account":
            # Balance updates
            pass

    async def _safety_poller(self, engine):
        """
        Periodically reconciles state via REST to handle missed WS events.
        """
        while True:
            try:
                await asyncio.sleep(60) # Poll every 60 seconds
                if engine.stop_event.is_set(): break
                await engine._sync_exchange_state()
            except Exception as e:
                log.error(f"Safety Poller Error: {e}")

    async def _process_orders(self):
        """
        [REPAIR-20260708] Overrides Simulator._process_orders for real exchange.
        In Live/Demo, we only handle entry timeouts. Fills/Exits are handled via Private WS.
        """
        now = time.time()
        for o in list(self.pending_orders):
            if o["type"] == "entry_limit":
                # Only handle timeouts
                if now - o.get("ts", now) > config.LIMIT_CHASE_TIMEOUT:
                    log.info(f"TIMEOUT: Cancelling stale limit entry for {o['symbol']} {o['pos_side'].upper()}")
                    if o in self.pending_orders:
                        self.used_margin -= o.get("reserved_margin", 0)
                        self.pending_orders.remove(o)

                    real_oid = o.get("orderId")
                    if real_oid:
                        asyncio.create_task(self.cancel_order(o['symbol'], real_oid))

                    if self.engine:
                        pos_key = f"{o['symbol']}_{o['pos_side']}"
                        if pos_key in self.engine.pending_entries:
                            self.engine.pending_entries.remove(pos_key)

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
            for t in data:
                # Bitget V2 trade format: [ts, price, size, side]
                price = float(t[1]) if isinstance(t, list) else float(t.get("price", 0))
                size = float(t[2]) if isinstance(t, list) else float(t.get("size", 0))
                ts_ms = float(t[0]) if isinstance(t, list) else float(t.get("ts", 0))
                ts = ts_ms / 1000
                side = t[3] if isinstance(t, list) else t.get("side", "buy")

                self.last_price[norm_sym] = price

                # Update trade history for feature extraction
                if norm_sym not in self.trade_history: self.trade_history[norm_sym] = []
                self.trade_history[norm_sym].append({"price": price, "size": size, "side": side, "ts": ts})
                if len(self.trade_history[norm_sym]) > 200: self.trade_history[norm_sym].pop(0)

                if self.db:
                    self.db.save_tick(norm_sym, ts, price, side, size)

                # [REPAIR-20260708] Update real-time candles in simulator
                self._update_candles(norm_sym, price, size, ts)

    async def close(self):
        # Simulator (parent) might have its own close or needs its client closed
        if hasattr(self, "data_client"):
            await self.data_client.close()
        if hasattr(self, "client_exec"):
            await self.client_exec.close()
        if self.ws_client:
            self.ws_client.stop()
        if self.ws_private:
            self.ws_private.stop()
