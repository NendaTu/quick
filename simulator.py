import asyncio, time, logging, math, random
from typing import Dict, List, Tuple, Optional
from config import *
from orderbook import SimulatedOrderBook
from indicators import (
    compute_rsi, compute_atr, compute_ema, compute_macd, compute_supertrend, compute_drt
)
from database import Database
from bitget_client import BitGetClient, BitGetWSClient

log = logging.getLogger("scalper.simulator")

class Simulator:
    def __init__(self):
        self.books: Dict[str, SimulatedOrderBook] = {}
        self.leverage_limits = LEVERAGE_LIMITS.copy()
        self.equity = INITIAL_EQUITY
        self.used_margin = 0.0

        self.positions: Dict[Tuple[str, str], dict] = {}
        self.pending_orders: List[dict] = []
        self.order_id_counter = 1000
        self.total_realized_pnl = 0.0
        self.engine = None
        self.db = Database()
        self.client = BitGetClient(BITGET_API_KEY, BITGET_SECRET_KEY, BITGET_PASSPHRASE)

        self.ohlcv_1m: Dict[str, List[dict]] = {}
        self.confluence_history: Dict[str, Dict[str, List[float]]] = {}
        self.last_candle_ts: Dict[str, Dict[str, float]] = {}
        self.last_price: Dict[str, float] = {}

        all_assets = ASSETS + [BTC_SYMBOL]
        for sym in all_assets:
            self.books[sym] = SimulatedOrderBook(sym, BASE_PRICES.get(sym, 1.0))
            self.ohlcv_1m[sym] = []
            self.confluence_history[sym] = {"15m": [], "1H": [], "4H": [], "1D": []}
            self.last_candle_ts[sym] = {"1m": 0, "15m": 0, "1H": 0, "4H": 0, "1D": 0}
            self.last_price[sym] = BASE_PRICES.get(sym, 1.0)

    async def warm_up(self):
        log.info("Starting data warm-up...")
        symbols = ASSETS + [BTC_SYMBOL]
        semaphore = asyncio.Semaphore(10) # Respect rate limits

        async def fetch_symbol_data(sym):
            async with semaphore:
                # 1. Fetch 1m candles for indicators
                m1_data = await self.client.get_candles(sym, "1m", limit=500)
                if isinstance(m1_data, list):
                    for c in reversed(m1_data):
                        ts = float(c[0]) / 1000
                        o, h, l, cl, v = map(float, c[1:6])
                        self.db.save_candle(sym, "1m", ts, o, h, l, cl, v)
                        self.ohlcv_1m[sym].append({"ts": ts, "o": o, "h": h, "l": l, "c": cl, "v": v})
                        self.last_candle_ts[sym]["1m"] = ts

                    if m1_data:
                        price = float(m1_data[0][4])
                        self.books[sym].mid_price = price
                        self.last_price[sym] = price
                        self.books[sym]._regenerate()
                else:
                    log.warning(f"Failed to fetch 1m candles for {sym}")

                # 2. Fetch confluence timeframes
                for tf in ["15m", "1H", "4H", "1D"]:
                    c_data = await self.client.get_candles(sym, tf, limit=100)
                    if isinstance(c_data, list):
                        for c in reversed(c_data):
                            ts = float(c[0]) / 1000
                            cl = float(c[4])
                            self.confluence_history[sym][tf].append(cl)
                            self.last_candle_ts[sym][tf] = ts
                    else:
                        log.warning(f"Failed to fetch {tf} candles for {sym}")

        await asyncio.gather(*(fetch_symbol_data(s) for s in symbols))
        log.info("Warm-up complete.")

    def get_features(self, symbol: str) -> Dict[str, float]:
        book = self.books.get(symbol)
        if not book: return {}

        bid_vol, ask_vol = book.top_bid_ask_qty()
        total_vol = bid_vol + ask_vol
        imbalance = (bid_vol - ask_vol) / total_vol if total_vol > 0 else 0.0
        mid = (book.best_bid + book.best_ask) / 2
        spread = book.best_ask - book.best_bid
        vol_pct = min(1.0, total_vol / 4000.0)

        history = self.ohlcv_1m.get(symbol, [])
        if len(history) < 50: return {}

        # Optimization: only take what we need
        relevant_history = history[-(INDICATOR_PRICE_HISTORY + 50):]
        closes = [x["c"] for x in relevant_history]
        highs = [x["h"] for x in relevant_history]
        lows = [x["l"] for x in relevant_history]

        rsi = compute_rsi(closes, RSI_PERIOD)
        atr = compute_atr(highs, lows, closes, ATR_PERIOD)
        macd, macd_signal, macd_hist = compute_macd(closes, MACD_FAST, MACD_SLOW, MACD_SIGNAL)
        ema_short = compute_ema(closes, EMA_SHORT)
        ema_long = compute_ema(closes, EMA_LONG)
        supertrend_val, supertrend_dir = compute_supertrend(highs, lows, closes, SUPERTREND_PERIOD, SUPERTREND_MULTIPLIER)
        drt = compute_drt(closes, 20)

        # Cache BTC changes globally per tick in the engine if possible,
        # but here we'll just keep it simple for now.
        btc_changes = {}
        for tf in ["15m", "1H", "4H", "1D"]:
            h = self.confluence_history[BTC_SYMBOL][tf]
            if len(h) >= 2:
                btc_changes[f"btc_{tf}"] = (h[-1] / h[-2] - 1)
            else:
                btc_changes[f"btc_{tf}"] = 0.0

        asset_changes = {}
        for tf in ["15m", "1H", "4H", "1D"]:
            h = self.confluence_history[symbol][tf]
            if len(h) >= 2:
                asset_changes[f"asset_{tf}"] = (h[-1] / h[-2] - 1)
            else:
                asset_changes[f"asset_{tf}"] = 0.0

        return {
            "imbalance": imbalance,
            "spread_pct": spread / mid if mid > 0 else 0,
            "vol_pct": vol_pct,
            "rsi": rsi,
            "atr": atr,
            "macd": macd,
            "macd_signal": macd_signal,
            "macd_hist": macd_hist,
            "ema_short": ema_short,
            "ema_long": ema_long,
            "supertrend": supertrend_val,
            "supertrend_dir": supertrend_dir,
            "drt": drt,
            **btc_changes,
            **asset_changes,
        }

    async def _ws_callback(self, msg):
        channel = msg.get("arg", {}).get("channel")
        instId = msg.get("arg", {}).get("instId")
        data = msg.get("data", [])
        if not data: return

        if channel == "books25":
            d = data[0]
            self.books[instId].bids = [(float(p), float(q)) for p, q in d.get("bids", [])]
            self.books[instId].asks = [(float(p), float(q)) for p, q in d.get("asks", [])]
            self.books[instId].mid_price = (self.books[instId].best_bid + self.books[instId].best_ask) / 2

        elif channel == "trade":
            for t in data:
                price = float(t[1]) if isinstance(t, list) else float(t.get("price", 0))
                size = float(t[2]) if isinstance(t, list) else float(t.get("size", 0))
                ts_ms = float(t[0]) if isinstance(t, list) else float(t.get("ts", 0))
                ts = ts_ms / 1000
                side = t[3] if isinstance(t, list) else t.get("side", "buy")

                self.last_price[instId] = price
                self.db.save_tick(instId, ts, price, side, size)
                self._update_candles(instId, price, size, ts)

    def _update_candles(self, symbol, price, size, ts):
        tf_map = {"1m": 60, "15m": 900, "1H": 3600, "4H": 14400, "1D": 86400}
        for tf_name, seconds in tf_map.items():
            candle_start = (ts // seconds) * seconds
            last_ts = self.last_candle_ts[symbol].get(tf_name, 0)

            if candle_start > last_ts:
                if tf_name == "1m":
                    self.ohlcv_1m[symbol].append({"ts": candle_start, "o": price, "h": price, "l": price, "c": price, "v": size})
                    if len(self.ohlcv_1m[symbol]) > 1000: self.ohlcv_1m[symbol].pop(0)
                    prev = self.ohlcv_1m[symbol][-2] if len(self.ohlcv_1m[symbol]) > 1 else None
                    if prev:
                        self.db.save_candle(symbol, "1m", prev["ts"], prev["o"], prev["h"], prev["l"], prev["c"], prev["v"])
                else:
                    self.confluence_history[symbol][tf_name].append(price)
                    if len(self.confluence_history[symbol][tf_name]) > 200: self.confluence_history[symbol][tf_name].pop(0)
                self.last_candle_ts[symbol][tf_name] = candle_start
            else:
                if tf_name == "1m":
                    if self.ohlcv_1m[symbol]:
                        curr = self.ohlcv_1m[symbol][-1]
                        curr["h"] = max(curr["h"], price)
                        curr["l"] = min(curr["l"], price)
                        curr["c"] = price
                        curr["v"] += size
                else:
                    if self.confluence_history[symbol][tf_name]:
                        self.confluence_history[symbol][tf_name][-1] = price

    async def data_feed_task(self, engine):
        symbols = ASSETS + [BTC_SYMBOL]
        ws_client = BitGetWSClient(symbols, self._ws_callback)
        asyncio.create_task(ws_client.run())

        last_heartbeat = time.time()
        while True:
            for sym in symbols:
                book = self.books[sym]
                engine.books[sym].bids = list(book.bids)
                engine.books[sym].asks = list(book.asks)
                engine.books[sym].timestamp = time.time()

            await self._process_orders()
            engine.equity = self.equity

            # Heartbeat log
            now = time.time()
            if now - last_heartbeat > 60:
                log.debug("Simulator data_feed heartbeat")
                last_heartbeat = now

            await asyncio.sleep(0.1)

    async def _process_orders(self):
        fills = []
        if self.pending_orders:
            # log.debug(f"Checking {len(self.pending_orders)} pending orders")
            pass
        for o in list(self.pending_orders):
            sym = o["symbol"]
            side = o["pos_side"]
            price = self.last_price.get(sym)
            if not price: continue

            if o["type"] == "stop":
                if side == "buy" and price <= o["triggerPrice"]: fills.append((o, "stop"))
                elif side == "sell" and price >= o["triggerPrice"]: fills.append((o, "stop"))
            elif o["type"] == "tp":
                if side == "buy" and price >= o["price"]: fills.append((o, "tp"))
                elif side == "sell" and price <= o["price"]: fills.append((o, "tp"))

        for o, et in fills:
            await asyncio.sleep(random.uniform(0.02, 0.05))
            exit_action = "sell" if o["pos_side"] == "buy" else "buy"
            fill_price = self._calculate_fill_price(o["symbol"], exit_action, o["qty"])
            self._execute_exit(o, fill_price, et)
            if o in self.pending_orders:
                self.pending_orders.remove(o)

    def get_leverage_limits(self):
        return self.leverage_limits

    def _calculate_fill_price(self, symbol, side, qty):
        book = self.books[symbol]
        levels = book.asks if side == "buy" else book.bids
        filled_qty = 0
        total_cost = 0
        if not levels: return self.last_price.get(symbol, 0)

        for price, size in levels:
            take = min(qty - filled_qty, size)
            total_cost += take * price
            filled_qty += take
            if filled_qty >= qty: break

        if filled_qty < qty:
            total_cost += (qty - filled_qty) * (levels[-1][0] if levels else self.last_price.get(symbol, 0)) * 1.01
        return total_cost / qty if qty > 0 else 0

    def place_trade_oco(self, symbol, side, qty, entry_price, stop_price, tp_price, btc_conf=""):
        max_lev = self.leverage_limits.get(symbol, 20)
        required_margin = (qty * entry_price) / max_lev

        available_balance = self.equity - self.used_margin
        if available_balance < required_margin:
            return {"code": "1", "msg": "insufficient balance"}

        fill_price = self._calculate_fill_price(symbol, side, qty)

        # SLIPPAGE CONTROL
        slippage = (fill_price / entry_price - 1) if side == "buy" else (entry_price / fill_price - 1)
        if slippage > MAX_ENTRY_SLIPPAGE:
            if LOG_REJECTIONS:
                log.warning(f"REJECTED {symbol} {side.upper()}: High slippage {slippage*100:.3f}% > {MAX_ENTRY_SLIPPAGE*100}%")
            return {"code": "2", "msg": "high slippage"}

        self._execute_entry_direct(symbol, side, qty, fill_price, btc_conf)

        sid = self.order_id_counter; self.order_id_counter += 1
        tid = self.order_id_counter; self.order_id_counter += 1

        self.pending_orders.extend([
            {"id": sid, "symbol": symbol, "pos_side": side, "type": "stop", "triggerPrice": stop_price, "qty": qty},
            {"id": tid, "symbol": symbol, "pos_side": side, "type": "tp", "price": tp_price, "qty": qty},
        ])
        return {"code": "00000", "data": {"orderId": str(sid)}}

    def _execute_entry_direct(self, symbol, side, qty, fill_price, btc_conf):
        fee = qty * fill_price * TAKER_FEE
        self.equity -= fee

        max_lev = self.leverage_limits.get(symbol, 20)
        margin = (qty * fill_price) / max_lev
        self.used_margin += margin

        self.positions[(symbol, side)] = {
            "side": side, "qty": qty, "entry_price": fill_price, "entry_fee": fee, "btc_conf": btc_conf, "margin": margin
        }
        log.info(f"FILLED ENTRY {symbol} {side.upper()} {qty:.3f} @ {fill_price:.8f} [{btc_conf}] | equity={self.equity:.2f} used_margin={self.used_margin:.2f}")

    def _execute_exit(self, order, fill_price, exit_type):
        sym = order["symbol"]
        side = order["pos_side"]
        pos = self.positions.get((sym, side))
        if not pos: return

        qty = min(order["qty"], pos["qty"])
        if side == "buy":
            pnl = (fill_price - pos["entry_price"]) * qty
        else:
            pnl = (pos["entry_price"] - fill_price) * qty

        fee = qty * fill_price * TAKER_FEE
        round_trip_pnl = pnl - fee - pos["entry_fee"]
        self.equity += (pnl - fee)
        self.used_margin -= pos.get("margin", 0)
        self.used_margin = max(0, self.used_margin)

        log.info(f"EXIT {sym} {side.upper()} {exit_type.upper()} @ {fill_price:.8f} PnL={pnl:.4f} net={round_trip_pnl:.4f} [{pos['btc_conf']}] | equity={self.equity:.2f} used_margin={self.used_margin:.2f}")

        del self.positions[(sym, side)]
        self.pending_orders = [o for o in self.pending_orders if not (o["symbol"] == sym and o["pos_side"] == side)]

        if self.engine: self.engine._report_exit(sym, side, round_trip_pnl)
