import asyncio, time, logging, math, random
from typing import Dict, List, Tuple
from config import *
from orderbook import SimulatedOrderBook
from indicators import (
    compute_rsi, compute_atr, compute_ema, compute_macd, compute_supertrend, compute_drt
)

log = logging.getLogger("scalper.simulator")

class Simulator:
    def __init__(self):
        self.books: Dict[str, SimulatedOrderBook] = {}
        self.leverage_limits = LEVERAGE_LIMITS.copy()
        self.equity = INITIAL_EQUITY
        self.positions: Dict[str, dict] = {}
        self.pending_orders: List[dict] = []
        self.order_id_counter = 1000
        self.total_realized_pnl = 0.0
        self._imbalance_state = {}
        self.engine = None

        self.price_history: Dict[str, List[float]] = {}
        self.high_history: Dict[str, List[float]] = {}
        self.low_history: Dict[str, List[float]] = {}
        self.close_history: Dict[str, List[float]] = {}

        all_assets = ASSETS + [BTC_SYMBOL]
        for sym in all_assets:
            price = BASE_PRICES.get(sym, 1.0)
            self.books[sym] = SimulatedOrderBook(sym, price)
            self._imbalance_state[sym] = random.uniform(-0.3, 0.3)
            self.price_history[sym] = [price] * (INDICATOR_PRICE_HISTORY + 1)
            self.high_history[sym] = [price * 1.0001] * (INDICATOR_PRICE_HISTORY + 1)
            self.low_history[sym] = [price * 0.9999] * (INDICATOR_PRICE_HISTORY + 1)
            self.close_history[sym] = [price] * (INDICATOR_PRICE_HISTORY + 1)

    def get_features(self, symbol: str) -> Dict[str, float]:
        book = self.books[symbol]
        bid_vol, ask_vol = book.top_bid_ask_qty()
        total_vol = bid_vol + ask_vol
        imbalance = (bid_vol - ask_vol) / total_vol if total_vol > 0 else 0.0
        mid = (book.best_bid + book.best_ask) / 2
        spread = book.best_ask - book.best_bid

        vol_pct = min(1.0, total_vol / 4000.0)

        prices = self.price_history[symbol]
        highs = self.high_history[symbol]
        lows = self.low_history[symbol]
        closes = self.close_history[symbol]

        rsi = compute_rsi(prices, RSI_PERIOD)
        atr = compute_atr(highs, lows, closes, ATR_PERIOD)
        macd, macd_signal, macd_hist = compute_macd(prices, MACD_FAST, MACD_SLOW, MACD_SIGNAL)
        ema_short = compute_ema(prices, EMA_SHORT)
        ema_long = compute_ema(prices, EMA_LONG)
        supertrend = compute_supertrend(highs, lows, closes, SUPERTREND_PERIOD, SUPERTREND_MULTIPLIER)
        drt = compute_drt(prices, 20)

        btc_prices = self.price_history[BTC_SYMBOL]
        btc_changes = {}
        for tf, ticks in TF_TICKS.items():
            if len(btc_prices) >= ticks:
                btc_changes[f"btc_{tf}"] = (btc_prices[-1] / btc_prices[-ticks] - 1) if btc_prices[-ticks] != 0 else 0.0
            else:
                btc_changes[f"btc_{tf}"] = 0.0

        asset_changes = {}
        for tf, ticks in TF_TICKS.items():
            if len(prices) >= ticks:
                asset_changes[f"asset_{tf}"] = (prices[-1] / prices[-ticks] - 1) if prices[-ticks] != 0 else 0.0
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
            "supertrend": supertrend,
            "drt": drt,
            **btc_changes,
            **asset_changes,
        }

    def get_leverage_limits(self):
        return self.leverage_limits

    async def data_feed_task(self, engine):
        sigma = SIM_SIGMA
        while True:
            for sym in self.books:
                book = self.books[sym]
                imb = self._imbalance_state[sym]
                signal_strength = SIM_SIGNAL_STRENGTH
                noise = random.gauss(0, sigma)
                log_return = signal_strength * imb + noise

                self._imbalance_state[sym] += random.gauss(0, SIM_IMBALANCE_NOISE)
                self._imbalance_state[sym] = max(-0.5, min(0.5, self._imbalance_state[sym]))

                book.random_step(math.exp(log_return))

                mid = (book.best_bid + book.best_ask) / 2
                high = book.best_ask * 1.0001
                low = book.best_bid * 0.9999
                self.price_history[sym].append(mid)
                self.high_history[sym].append(high)
                self.low_history[sym].append(low)
                self.close_history[sym].append(mid)

                if len(self.price_history[sym]) > INDICATOR_PRICE_HISTORY + 100:
                    self.price_history[sym] = self.price_history[sym][-INDICATOR_PRICE_HISTORY - 100:]
                    self.high_history[sym] = self.high_history[sym][-INDICATOR_PRICE_HISTORY - 100:]
                    self.low_history[sym] = self.low_history[sym][-INDICATOR_PRICE_HISTORY - 100:]
                    self.close_history[sym] = self.close_history[sym][-INDICATOR_PRICE_HISTORY - 100:]

                engine.books[sym].bids = [(p, s) for p, s in book.bids]
                engine.books[sym].asks = [(p, s) for p, s in book.asks]
                engine.books[sym].timestamp = time.time()

            orders_snapshot = list(self.pending_orders)
            fills_exit = []

            for o in orders_snapshot:
                sym = o["symbol"]
                book = self.books[sym]
                mid = book.mid_price

                if o["type"] == "stop":
                    if o["side"] == "buy" and mid >= o["triggerPrice"]:
                        fills_exit.append((o, mid, "stop"))
                    elif o["side"] == "sell" and mid <= o["triggerPrice"]:
                        fills_exit.append((o, mid, "stop"))
                elif o["type"] == "tp":
                    if o["side"] == "sell" and mid >= o["price"]:
                        fills_exit.append((o, mid, "tp"))
                    elif o["side"] == "buy" and mid <= o["price"]:
                        fills_exit.append((o, mid, "tp"))

            for o, fp, et in fills_exit:
                self._execute_exit(o, fp, et)

            self.pending_orders = [o for o in self.pending_orders
                                   if not any(o["id"] == fo[0]["id"] for fo in fills_exit)]

            engine.equity = self.equity
            engine.open_positions = {
                sym: {"side": p["side"], "qty": p["qty"], "entry": p["entry_price"]}
                for sym, p in self.positions.items()
            }
            await asyncio.sleep(0.2)

    def place_trade_oco(self, symbol: str, side: str, qty: float,
                        entry_price: float, stop_price: float, tp_price: float):
        book = self.books[symbol]
        position_value = qty * entry_price
        required_margin = position_value / self.leverage_limits[symbol]
        if self.equity < required_margin:
            return {"code": "1", "msg": "insufficient balance"}

        if side == "buy":
            fill_price = book.best_ask
        else:
            fill_price = book.best_bid

        self._execute_entry_direct(symbol, side, qty, fill_price)

        sid = self.order_id_counter; self.order_id_counter += 1
        tid = self.order_id_counter; self.order_id_counter += 1

        self.pending_orders.extend([
            {"id": sid, "symbol": symbol, "type": "stop",
             "side": "sell" if side == "buy" else "buy",
             "triggerPrice": stop_price, "qty": qty},
            {"id": tid, "symbol": symbol, "type": "tp",
             "side": "sell" if side == "buy" else "buy",
             "price": tp_price, "qty": qty},
        ])
        log.info(f"PAPER OCO: {symbol} {side} qty={qty:.3f} entry={fill_price:.4f} "
                 f"stop={stop_price:.4f} tp={tp_price:.4f}")
        return {"code": "00000", "data": {"orderId": str(sid)}}

    def _execute_entry_direct(self, symbol, side, qty, fill_price):
        fee = qty * fill_price * TAKER_FEE
        self.equity -= fee
        self.total_realized_pnl -= fee

        feats = self.get_features(symbol) if hasattr(self, 'get_features') else {}
        current_drt = feats.get("drt", 0.5)
        self.positions[symbol] = {
            "side": side, "qty": qty,
            "entry_price": fill_price,
            "entry_fee": fee,
            "open_time": time.time(),
            "entry_drt": current_drt
        }
        log.info(f"FILLED ENTRY {symbol} {side} {qty:.3f} @ {fill_price:.4f} "
                 f"drt={current_drt:.3f} rsi={feats.get('rsi',50):.1f} "
                 f"macd={feats.get('macd',0):.4f} ema={feats.get('ema_short',0):.4f} "
                 f"vol={feats.get('vol_pct',0):.2f} | equity={self.equity:.2f}")

    def _execute_exit(self, order, fill_price, exit_type):
        sym = order["symbol"]
        pos = self.positions.get(sym)
        if not pos:
            return
        qty = min(order["qty"], pos["qty"])
        if pos["side"] == "buy":
            pnl = (fill_price - pos["entry_price"]) * qty
        else:
            pnl = (pos["entry_price"] - fill_price) * qty
        fee_rate = TAKER_FEE
        fee = qty * fill_price * fee_rate
        round_trip_pnl = pnl - fee - pos["entry_fee"]
        # Equity: add gross profit, deduct exit fee (entry fee already deducted)
        self.equity += pnl - fee
        self.total_realized_pnl += round_trip_pnl

        feats = self.get_features(sym) if hasattr(self, 'get_features') else {}
        exit_drt = feats.get("drt", 0.5)
        del self.positions[sym]
        log.info(f"EXIT {sym} {exit_type} @ {fill_price:.4f} PnL={pnl:.4f} fee={fee:.4f} "
                 f"entry_fee={pos['entry_fee']:.4f} net={round_trip_pnl:.4f} "
                 f"drt={exit_drt:.3f} rsi={feats.get('rsi',50):.1f} "
                 f"macd={feats.get('macd',0):.4f} ema={feats.get('ema_short',0):.4f} "
                 f"vol={feats.get('vol_pct',0):.2f} | equity={self.equity:.2f}")
        if self.engine is not None:
            self.engine._update_stats(round_trip_pnl)