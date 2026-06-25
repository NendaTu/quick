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
        self.leverage_limits = {}
        self.contract_specs: Dict[str, dict] = {}
        self.equity = INITIAL_EQUITY
        self.used_margin = 0.0

        self.positions: Dict[Tuple[str, str], dict] = {}
        self.pending_orders: List[dict] = []
        self.order_id_counter = 1000
        self.total_realized_pnl = 0.0
        self.engine = None
        self.db = Database()
        self.client = BitGetClient(BITGET_API_KEY, BITGET_SECRET_KEY, BITGET_PASSPHRASE)

        self.ohlcv: Dict[str, Dict[str, List[dict]]] = {}
        self.confluence_history: Dict[str, Dict[str, List[float]]] = {}
        self.last_candle_ts: Dict[str, Dict[str, float]] = {}
        self.last_price: Dict[str, float] = {}
        self._btc_confluence_cache = {}
        self._last_confluence_update = 0
        self.discovered_assets: List[str] = []

    async def warm_up(self):
        log.info("Discovering top assets and starting warm-up...")

        # 1. Discover Assets by Volume
        tickers = await self.client.get_tickers()
        # Sort by usdtVolume descending
        sorted_tickers = sorted(tickers, key=lambda x: float(x.get("usdtVolume", 0)), reverse=True)

        discovered = []
        for t in sorted_tickers:
            sym = t["symbol"]
            # Filter: only USDT futures, not omitted, not stablecoins (proxy: ends with USDT)
            if sym.endswith("USDT") and sym not in ASSET_OMITTED:
                # Exclude known stables if they show up in volume
                if sym.replace("USDT", "") in ["USDC", "DAI", "BUSD", "EUR", "GBP"]:
                    continue
                discovered.append(sym)
                if len(discovered) >= ASSETS_COUNT:
                    break

        self.discovered_assets = discovered
        log.info(f"Top {len(discovered)} assets discovered by volume.")

        # 2. Fetch contract specs for discovered assets
        specs = await self.client.get_symbols()
        spec_map = {s['symbol']: s for s in specs}

        for sym in self.discovered_assets + [BTC_SYMBOL]:
            s = spec_map.get(sym)
            if s:
                self.contract_specs[sym] = s
                self.leverage_limits[sym] = float(s.get('maxLever', 20))
                # Initialize structures
                price = float(next((t['lastPr'] for t in tickers if t['symbol'] == sym), 1.0))
                self.books[sym] = SimulatedOrderBook(sym, price)
                self.ohlcv[sym] = {tf: [] for tf in AVAILABLE_TIMEFRAMES}
                self.confluence_history[sym] = {tf: [] for tf in ["15m", "1H", "4H", "1D"]}
                self.last_candle_ts[sym] = {tf: 0 for tf in AVAILABLE_TIMEFRAMES}
                self.last_price[sym] = price

        symbols = self.discovered_assets + [BTC_SYMBOL]
        semaphore = asyncio.Semaphore(5) # Reduced to stay within strict limits

        async def fetch_symbol_data(sym):
            async with semaphore:
                # Add a small staggered delay to prevent burst 429s
                await asyncio.sleep(0.1 * random.random())
                # 1. Fetch OHLCV for all relevant timeframes
                for tf in AVAILABLE_TIMEFRAMES:
                    limit = 500 if tf == "1m" else 100
                    data = await self.client.get_candles(sym, tf, limit=limit)
                    if isinstance(data, list):
                        for c in reversed(data):
                            ts = float(c[0]) / 1000
                            o, h, l, cl, v = map(float, c[1:6])
                            if tf == "1m":
                                self.db.save_candle(sym, "1m", ts, o, h, l, cl, v)
                            self.ohlcv[sym][tf].append({"ts": ts, "o": o, "h": h, "l": l, "c": cl, "v": v})
                            self.last_candle_ts[sym][tf] = ts

                        if tf == "1m" and data:
                            price = float(data[0][4])
                            self.books[sym].mid_price = price
                            self.last_price[sym] = price
                            self.books[sym]._regenerate()
                    else:
                        log.warning(f"Failed to fetch {tf} candles for {sym}")

                # 2. Fetch confluence history (closes only)
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

        def get_ohlc(tf):
            h = self.ohlcv.get(symbol, {}).get(tf, [])
            if not h: return [], [], []
            relevant = h[-(INDICATOR_PRICE_HISTORY + 50):]
            return [x["c"] for x in relevant], [x["h"] for x in relevant], [x["l"] for x in relevant]

        # RSI (1m)
        c1, _, _ = get_ohlc(INDICATOR_TIMEFRAMES["rsi"])
        rsi = compute_rsi(c1, RSI_PERIOD) if len(c1) > 20 else 50.0

        # MACD (1m)
        c1, _, _ = get_ohlc(INDICATOR_TIMEFRAMES["macd"])
        macd, macd_signal, macd_hist = compute_macd(c1, MACD_FAST, MACD_SLOW, MACD_SIGNAL) if len(c1) > 30 else (0,0,0)

        # ATR (1m)
        c1, h1, l1 = get_ohlc(INDICATOR_TIMEFRAMES["atr"])
        atr = compute_atr(h1, l1, c1, ATR_PERIOD) if len(c1) > 20 else 0.0

        # Supertrend (1m)
        supertrend_val, supertrend_dir = compute_supertrend(h1, l1, c1, SUPERTREND_PERIOD, SUPERTREND_MULTIPLIER) if len(c1) > 20 else (0, 0)

        # DRT SLOW (15m)
        cs, _, _ = get_ohlc(INDICATOR_TIMEFRAMES["drt_slow"])
        drt_slow = compute_drt(cs, 20) if len(cs) >= 20 else 0.5

        # DRT FAST (5m)
        cf, _, _ = get_ohlc(INDICATOR_TIMEFRAMES["drt_fast"])
        drt_fast = compute_drt(cf, 20) if len(cf) >= 20 else 0.5

        # Legacy DRT for backwards compatibility in logs
        drt = compute_drt(c1, 20) if len(c1) >= 20 else 0.5

        # BTC confluence cache (global per tick)
        now = time.time()
        if now - self._last_confluence_update > 0.1: # Update cache every 100ms
            self._btc_confluence_cache = {}
            for tf in ["15m", "1H", "4H", "1D"]:
                h = self.confluence_history[BTC_SYMBOL][tf]
                if len(h) >= 2:
                    self._btc_confluence_cache[f"btc_{tf}"] = (h[-1] / h[-2] - 1)
                else:
                    self._btc_confluence_cache[f"btc_{tf}"] = 0.0
            self._last_confluence_update = now

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
            "mid": mid,
            "vol_pct": vol_pct,
            "rsi": rsi,
            "atr": atr,
            "macd": macd,
            "macd_signal": macd_signal,
            "macd_hist": macd_hist,
            "drt": drt,
            "drt_slow": drt_slow,
            "drt_fast": drt_fast,
            **self._btc_confluence_cache,
            **asset_changes,
        }

    async def _ws_callback(self, msg):
        channel = msg.get("arg", {}).get("channel")
        instId = msg.get("arg", {}).get("instId")
        data = msg.get("data", [])
        if not data: return

        if channel == "books15":
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
        tf_map = {
            "1m": 60, "5m": 300, "15m": 900, "30m": 1800,
            "1H": 3600, "4H": 14400, "1D": 86400
        }
        for tf_name, seconds in tf_map.items():
            if tf_name not in AVAILABLE_TIMEFRAMES: continue

            candle_start = (ts // seconds) * seconds
            last_ts = self.last_candle_ts[symbol].get(tf_name, 0)

            if candle_start > last_ts:
                # New candle
                self.ohlcv[symbol][tf_name].append({"ts": candle_start, "o": price, "h": price, "l": price, "c": price, "v": size})
                if len(self.ohlcv[symbol][tf_name]) > 1000: self.ohlcv[symbol][tf_name].pop(0)

                # Persistence for 1m
                if tf_name == "1m":
                    prev = self.ohlcv[symbol][tf_name][-2] if len(self.ohlcv[symbol][tf_name]) > 1 else None
                    if prev:
                        self.db.save_candle(symbol, "1m", prev["ts"], prev["o"], prev["h"], prev["l"], prev["c"], prev["v"])

                # Update confluence history if it's a tracking timeframe
                if tf_name in self.confluence_history[symbol]:
                    self.confluence_history[symbol][tf_name].append(price)
                    if len(self.confluence_history[symbol][tf_name]) > 200: self.confluence_history[symbol][tf_name].pop(0)

                self.last_candle_ts[symbol][tf_name] = candle_start
            else:
                # Update current candle
                if self.ohlcv[symbol][tf_name]:
                    curr = self.ohlcv[symbol][tf_name][-1]
                    curr["h"] = max(curr["h"], price)
                    curr["l"] = min(curr["l"], price)
                    curr["c"] = price
                    curr["v"] += size

                    if tf_name in self.confluence_history[symbol]:
                        self.confluence_history[symbol][tf_name][-1] = price

    async def data_feed_task(self, engine):
        symbols = self.discovered_assets + [BTC_SYMBOL]
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
        now = time.time()
        for o in list(self.pending_orders):
            sym = o["symbol"]
            side = o["pos_side"]
            price = self.last_price.get(sym)
            if not price: continue

            # Breakeven Trigger Logic
            if USE_BREAKEVEN_TRIGGER and o["type"] == "stop":
                pos = self.positions.get((sym, side))
                if pos and not o.get("is_breakeven"):
                    entry = pos["entry_price"]
                    max_lev = self.leverage_limits.get(sym, 20)

                    # Calculate current ROE
                    if side == "buy":
                        roe = (price / entry - 1) * max_lev
                    else:
                        roe = (entry / price - 1) * max_lev

                    if roe >= BREAKEVEN_ROI_THRESHOLD:
                        # Move SL to Entry + small buffer (0.05%) to cover partial fees
                        buffer = 0.0005
                        o["triggerPrice"] = entry * (1 + buffer) if side == "buy" else entry * (1 - buffer)
                        o["is_breakeven"] = True
                        log.info(f"BREAKEVEN TRIGGERED for {sym} {side.upper()} @ ROE={roe*100:.2f}% | SL moved to {o['triggerPrice']:.8f}")

            if o["type"] == "entry_limit":
                # Check if price reached our limit
                # For a BUY limit, price must be <= limit
                # For a SELL limit, price must be >= limit
                if side == "buy" and price <= o["price"]: fills.append((o, "entry"))
                elif side == "sell" and price >= o["price"]: fills.append((o, "entry"))

                # Chase/Timeout logic
                elif now - o.get("ts", now) > LIMIT_CHASE_TIMEOUT:
                    # In a real bot, we'd reposition. For simulation, let's just "take" it
                    # to keep the data flowing, or expire it. Let's convert to market-ish fill.
                    fills.append((o, "entry_timeout"))

            elif o["type"] == "stop":
                # Soft Stop Logic
                if SL_ORDER_TYPE == "limit":
                    # Check if price reached our limit (for BUY stop, price <= limit)
                    if side == "buy" and price <= o["triggerPrice"]: fills.append((o, "stop"))
                    elif side == "sell" and price >= o["triggerPrice"]: fills.append((o, "stop"))

                    # Disaster Backup: If price moves TOO FAR past our limit, market fill
                    else:
                        # Side is 'buy' (Long position): Exit if price CRASHES below our limit
                        # Side is 'sell' (Short position): Exit if price MOONS above our limit
                        if side == "buy": # Long
                            distance = (o["triggerPrice"] / price - 1)
                        else: # Short
                            distance = (price / o["triggerPrice"] - 1)

                        # Only fire if distance is positive (price bypassed limit) AND exceeds buffer
                        if distance > SL_DISASTER_BUFFER:
                            fills.append((o, "stop_disaster"))
                else:
                    # Market Stop
                    if side == "buy" and price <= o["triggerPrice"]: fills.append((o, "stop"))
                    elif side == "sell" and price >= o["triggerPrice"]: fills.append((o, "stop"))
            elif o["type"] == "tp":
                if side == "buy" and price >= o["price"]: fills.append((o, "tp"))
                elif side == "sell" and price <= o["price"]: fills.append((o, "tp"))

        for o, et in fills:
            # Simulate realistic network latency and engine processing time
            latency = random.lognormvariate(math.log(0.035), 0.4)
            await asyncio.sleep(max(0.01, min(0.3, latency)))

            if et in ["entry", "entry_timeout"]:
                # Maker fill if et == "entry", else Taker
                order_type = "limit" if et == "entry" else "market"
                # If timeout, we might get a worse price. For simplicity, use current market.
                fill_price = o["price"] if et == "entry" else self.last_price.get(o["symbol"])

                self._execute_entry_direct(o["symbol"], o["pos_side"], o["qty"], fill_price, o.get("btc_conf", ""), o.get("drt", 0.5), order_type, o.get("original_side"), o.get("is_contrarian", False))

                # Once entry is filled, add TP/SL
                sid = self.order_id_counter; self.order_id_counter += 1
                tid = self.order_id_counter; self.order_id_counter += 1
                self.pending_orders.extend([
                    {"id": sid, "symbol": o["symbol"], "pos_side": o["pos_side"], "type": "stop", "triggerPrice": o["stop_price"], "qty": o["qty"], "original_side": o.get("original_side"), "is_contrarian": o.get("is_contrarian", False)},
                    {"id": tid, "symbol": o["symbol"], "pos_side": o["pos_side"], "type": "tp", "price": o["tp_price"], "qty": o["qty"], "original_side": o.get("original_side"), "is_contrarian": o.get("is_contrarian", False)},
                ])
            else:
                if et == "stop_disaster":
                    order_type = "market"
                    exit_type = "stop_backup"
                else:
                    order_type = TP_ORDER_TYPE if et == "tp" else SL_ORDER_TYPE
                    exit_type = et

                exit_action = "sell" if o["pos_side"] == "buy" else "buy"

                # Use limit price if it's a limit order, else calculate slippage for market
                if order_type == "limit":
                    fill_price = o.get("price") or o.get("triggerPrice")
                else:
                    fill_price = self._calculate_fill_price(o["symbol"], exit_action, o["qty"])

                self._execute_exit(o, fill_price, exit_type, order_type)

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

        avg_price = total_cost / qty if qty > 0 else 0

        # Respect price precision for fill
        spec = self.contract_specs.get(symbol, {})
        price_place = int(spec.get('pricePlace', 2))
        return round(avg_price, price_place)

    def place_trade_oco(self, symbol, side, qty, entry_price, stop_price, tp_price, btc_conf="", drt=0.5, original_side=None, is_contrarian=False):
        spec = self.contract_specs.get(symbol, {})
        min_usdt = float(spec.get('minTradeUSDT', 5.0))
        if RESTRICT_MIN_VAL and qty * entry_price < min_usdt:
            return {"code": "3", "msg": f"order value below min {min_usdt}"}

        max_lev = self.leverage_limits.get(symbol, 20)
        required_margin = (qty * entry_price) / max_lev

        available_balance = self.equity - self.used_margin
        if available_balance < required_margin:
            return {"code": "1", "msg": "insufficient balance"}

        if ENTRY_ORDER_TYPE == "market":
            fill_price = self._calculate_fill_price(symbol, side, qty)

            # SLIPPAGE CONTROL
            slippage = (fill_price / entry_price - 1) if side == "buy" else (entry_price / fill_price - 1)
            if RESTRICT_SLIPPAGE and slippage > MAX_ENTRY_SLIPPAGE:
                rej_msg = f"REJECTED {symbol} {side.upper()}: High slippage {slippage*100:.3f}% > {MAX_ENTRY_SLIPPAGE*100}%"
                if LOG_REJECTIONS:
                    log.warning(rej_msg)
                else:
                    log.debug(rej_msg) # Log as debug so it goes to DB but not console
                return {"code": "2", "msg": "high slippage"}

            self._execute_entry_direct(symbol, side, qty, fill_price, btc_conf, drt, "market", original_side, is_contrarian)

            sid = self.order_id_counter; self.order_id_counter += 1
            tid = self.order_id_counter; self.order_id_counter += 1

            self.pending_orders.extend([
                {"id": sid, "symbol": symbol, "pos_side": side, "type": "stop", "triggerPrice": stop_price, "qty": qty, "original_side": original_side, "is_contrarian": is_contrarian},
                {"id": tid, "symbol": symbol, "pos_side": side, "type": "tp", "price": tp_price, "qty": qty, "original_side": original_side, "is_contrarian": is_contrarian},
            ])
            return {"code": "00000", "data": {"orderId": str(sid)}}
        else:
            # Limit Entry
            eid = self.order_id_counter; self.order_id_counter += 1
            self.pending_orders.append({
                "id": eid, "symbol": symbol, "pos_side": side, "type": "entry_limit",
                "price": entry_price, "qty": qty, "ts": time.time(),
                "stop_price": stop_price, "tp_price": tp_price,
                "btc_conf": btc_conf, "drt": drt,
                "original_side": original_side, "is_contrarian": is_contrarian
            })
            side_str = side.upper()
            if is_contrarian:
                side_str = f"{original_side.upper()} [Flipped to {side.upper()}]"
            log.info(f"PLACED LIMIT ENTRY {symbol} {side_str} {qty:.3f} @ {entry_price:.8f}")
            return {"code": "00000", "data": {"orderId": str(eid)}}

    def _execute_entry_direct(self, symbol, side, qty, fill_price, btc_conf, drt=0.5, order_type="market", original_side=None, is_contrarian=False):
        fee_rate = MAKER_FEE if order_type == "limit" else TAKER_FEE
        fee = qty * fill_price * fee_rate
        self.equity -= fee

        max_lev = self.leverage_limits.get(symbol, 20)
        margin = (qty * fill_price) / max_lev
        self.used_margin += margin

        self.positions[(symbol, side)] = {
            "side": side, "qty": qty, "entry_price": fill_price, "entry_fee": fee, "btc_conf": btc_conf, "margin": margin, "entry_drt": drt,
            "original_side": original_side, "is_contrarian": is_contrarian
        }
        side_str = side.upper()
        if is_contrarian:
            side_str = f"{(original_side or side).upper()} [Flipped to {side.upper()}]"

        log.info(f"FILLED ENTRY {symbol} {side_str} {qty:.3f} @ {fill_price:.8f} ({order_type.upper()}) [{btc_conf}] drt={drt:.4f} | equity={self.equity:.2f} used_margin={self.used_margin:.2f}")

        if self.engine:
            self.engine._report_entry(symbol, side, qty, fill_price, original_side, is_contrarian)

    def _execute_exit(self, order, fill_price, exit_type, order_type="market"):
        sym = order["symbol"]
        side = order["pos_side"]
        pos = self.positions.get((sym, side))
        if not pos: return

        # Fetch real-time DRT for exit audit
        exit_features = self.get_features(sym)
        exit_drt = exit_features.get("drt", 0.5)

        qty = min(order["qty"], pos["qty"])
        if side == "buy":
            pnl = (fill_price - pos["entry_price"]) * qty
        else:
            pnl = (pos["entry_price"] - fill_price) * qty

        fee_rate = MAKER_FEE if order_type == "limit" else TAKER_FEE
        fee = qty * fill_price * fee_rate
        round_trip_pnl = pnl - fee - pos["entry_fee"]
        self.equity += (pnl - fee)
        self.used_margin -= pos.get("margin", 0)
        self.used_margin = max(0, self.used_margin)

        side_str = side.upper()
        if pos.get("is_contrarian"):
            side_str = f"{pos.get('original_side', side).upper()} [Flipped to {side.upper()}]"

        log.info(f"EXIT {sym} {side_str} {exit_type.upper()} ({order_type.upper()}) @ {fill_price:.8f} PnL={pnl:.4f} net={round_trip_pnl:.4f} "
                 f"[{pos['btc_conf']}] drt_entry={pos.get('entry_drt',0.5):.4f} drt_exit={exit_drt:.4f} | "
                 f"equity={self.equity:.2f} used_margin={self.used_margin:.2f}")

        del self.positions[(sym, side)]
        self.pending_orders = [o for o in self.pending_orders if not (o["symbol"] == sym and o["pos_side"] == side)]

        if self.engine: self.engine._report_exit(sym, side, round_trip_pnl)
