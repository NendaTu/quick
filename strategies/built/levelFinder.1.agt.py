"""
1. Summary: Multi-timeframe order block level finder and trade executor.
2. Description: Identifies institutional order blocks on 1m, 3m, 5m, and 15m intervals. Takes entries on solidified candle closures, with a three-way split take profit target model.
3. Context: Relies on ta/patterns/ob.py for pattern identification. Extensively backtested in multi-variant portfolios.
"""
import logging
from typing import Dict, Optional, Any, List
from strategies.base_strategy import JBaseStrategy
from ta.patterns.ob import detect_order_blocks
from tools.trading_utils import (
    calculate_position_size,
    calculate_target_roe_for_rrr,
    calculate_tp_for_roe,
    format_order_quantity,
    get_price_precision
)
import config

class LevelFinderStrategy(JBaseStrategy):
    def __init__(self, config_overrides: Optional[Dict] = None, simulator=None):
        super().__init__(
            name="levelFinder",
            version="1",
            author="agt",
            config_overrides=config_overrides
        )
        self.simulator = simulator

        self.params = {
            "timeframes": ["1m", "3m", "5m", "15m"],
            "ob_period": 14,
            "impulse_mult": 1.5,
            "entry_order_type": "market" # Market orders ensure 100% instant fills on OB solidification candle close
        }

        # Warm-up history requirements for all timeframes
        self.required_history = {tf: self.params["ob_period"] + 100 for tf in self.params["timeframes"]}
        self.last_analyzed_ts = {}

        if config_overrides:
            for k in self.params:
                if k in config_overrides:
                    self.params[k] = config_overrides[k]

    def get_entry_signal(self, market_data: Dict) -> Optional[Dict]:
        symbol = market_data["symbol"]
        if symbol not in self.last_analyzed_ts:
            self.last_analyzed_ts[symbol] = {}

        # Loop through each timeframe to discover solidified order blocks
        for tf in self.params["timeframes"]:
            ohlcv = self._get_ohlcv(symbol, tf)
            if not ohlcv or len(ohlcv) < self.required_history[tf]:
                continue

            solidify_ts = ohlcv[-2]["ts"]
            if self.last_analyzed_ts[symbol].get(tf) == solidify_ts:
                continue

            self.last_analyzed_ts[symbol][tf] = solidify_ts

            # 1. Detect order blocks using stateless module
            res = detect_order_blocks(ohlcv, period=self.params["ob_period"], impulse_mult=self.params["impulse_mult"])
            all_obs = res.get("all_obs", [])
            if not all_obs:
                continue

            # 2. Check if a new order block was just solidified (formed) at the most recently closed candle
            # closed_ohlcv has length len(ohlcv) - 1. The most recently closed candle is at index len(ohlcv) - 2.
            # The OB base candle 'curr' is at index len(ohlcv) - 3.
            # If an order block has 'index' == len(ohlcv) - 3, it was confirmed on the close of ohlcv[-2]!
            target_ob = None
            expected_ob_idx = len(ohlcv) - 3
            for ob in all_obs:
                if ob["index"] == expected_ob_idx and ob["state"] == "active":
                    target_ob = ob
                    break

            if not target_ob:
                continue

            # 3. Determine Entry details from this timeframe
            entry_side = "buy" if target_ob["type"] == "bullish" else "sell"
            entry_price = ohlcv[-2]["c"] # The close of the candle that solidified the OB

            # Precision specs
            price_place, tick_size = get_price_precision(symbol, self.simulator.contract_specs if self.simulator else None)

            # SL: 1 tick past the OB extreme
            if entry_side == "buy":
                stop_price = target_ob["bottom"] - tick_size
            else:
                stop_price = target_ob["top"] + tick_size

            # Enforce minimum stop-loss distance guard (at least SL_MOVE to avoid zero-width fee traps)
            min_stop_dist = entry_price * getattr(config, "SL_MOVE", 0.004)
            if abs(entry_price - stop_price) < min_stop_dist:
                if entry_side == "buy":
                    stop_price = entry_price - min_stop_dist
                else:
                    stop_price = entry_price + min_stop_dist

            stop_price = round(stop_price, price_place)

            # Leverage & TP targets
            leverage = int(self.simulator.leverage_limits.get(symbol, 20) if self.simulator else 20)
            entry_order_type = self.params["entry_order_type"]
            entry_maker = (entry_order_type == "limit")
            tp_maker = (config.TP_ORDER_TYPE == "limit")

            # TP1: 1:1 + fees and slippage
            target_roe_1 = calculate_target_roe_for_rrr(1.0, entry_price, stop_price, leverage, entry_maker=entry_maker, exit_maker=tp_maker)
            tp1_price = calculate_tp_for_roe(entry_price, target_roe_1, entry_side, leverage, entry_maker=entry_maker, exit_maker=tp_maker, include_slippage=True)

            # TP2: 1:2 + fees and slippage
            target_roe_2 = calculate_target_roe_for_rrr(2.0, entry_price, stop_price, leverage, entry_maker=entry_maker, exit_maker=tp_maker)
            tp2_price = calculate_tp_for_roe(entry_price, target_roe_2, entry_side, leverage, entry_maker=entry_maker, exit_maker=tp_maker, include_slippage=True)

            # TP3: 1:3 + fees and slippage
            target_roe_3 = calculate_target_roe_for_rrr(3.0, entry_price, stop_price, leverage, entry_maker=entry_maker, exit_maker=tp_maker)
            tp3_price = calculate_tp_for_roe(entry_price, target_roe_3, entry_side, leverage, entry_maker=entry_maker, exit_maker=tp_maker, include_slippage=True)

            tp1_price = round(tp1_price, price_place)
            tp2_price = round(tp2_price, price_place)
            tp3_price = round(tp3_price, price_place)

            # --- Account, Risk, & Compounding Integration [REPAIR] ---
            use_virtual = getattr(config, 'USE_VIRTUAL_BALANCE', False)
            starting_equity = getattr(config, 'INITIAL_EQUITY', 40.0)
            reinvest_pct = getattr(config, 'REINVESTMENT_PERCENTAGE', 1.0)
            risk_per_trade = getattr(config, 'RISK_PER_TRADE', 0.01)

            # Get total equity from simulator or market data
            total_equity = market_data.get("equity") or (self.simulator.equity if self.simulator else starting_equity)

            # Handle virtual balance override if enabled in live/demo mode
            if use_virtual and self.simulator and getattr(self.simulator, "mode", "paper") != "paper":
                total_equity = starting_equity # Under live/demo with USE_VIRTUAL_BALANCE, lock to initial equity for compounding baseline

            # Calculate riskable equity base for compounding
            if total_equity > starting_equity:
                riskable_equity = starting_equity + (total_equity - starting_equity) * reinvest_pct
            else:
                riskable_equity = total_equity

            qty = calculate_position_size(riskable_equity, risk_per_trade, entry_price, stop_price)

            # Quantities formatting according to specs
            qty, qty_place = format_order_quantity(
                qty,
                entry_price,
                total_equity,
                self.simulator.contract_specs if self.simulator else None,
                symbol,
                logger=self.logger
            )
            if qty is None:
                continue

            # Proportional 3-way quantity split (33% / 33% / 34%)
            tp1_qty = round(qty * 0.33, qty_place)
            tp2_qty = round(qty * 0.33, qty_place)
            tp3_qty = qty - tp1_qty - tp2_qty

            # Ensure quantities are non-zero tick size
            min_qty_tick = 1 / (10**qty_place)
            if tp1_qty < min_qty_tick or tp2_qty < min_qty_tick or tp3_qty < min_qty_tick:
                # Fallback to single take-profit if quantity too small
                tp1_qty = 0
                tp2_qty = 0
                tp3_qty = qty

            log_func = self.logger.info if getattr(config, "LOG_SIGNALS", True) else self.logger.debug
            log_func(f"[{symbol}] {target_ob['type'].upper()} OB Solidified on timeframe {tf} at index {target_ob['index']}!")
            log_func(f"  - Solidifying Candle Close (Entry): {entry_price:.8f}")
            log_func(f"  - Stop Loss: {stop_price:.8f}")
            log_func(f"  - TP1 (1:1): {tp1_price:.8f} (Qty: {tp1_qty})")
            log_func(f"  - TP2 (1:2): {tp2_price:.8f} (Qty: {tp2_qty})")
            log_func(f"  - TP3 (1:3): {tp3_price:.8f} (Qty: {tp3_qty})")

            return {
                "side": entry_side,
                "entry_price": entry_price,
                "stop_price": stop_price,
                "exit_price": tp3_price,
                "tp_price": tp3_price,
                "tp1_price": tp1_price,
                "tp1_qty": tp1_qty,
                "tp2_price": tp2_price,
                "tp2_qty": tp2_qty,
                "tp3_price": tp3_price,
                "tp3_qty": tp3_qty,
                "qty": qty,
                "range_candle_type": "bullish" if target_ob["type"] == "bullish" else "bearish",
                "entry_order_type": entry_order_type,
                "metadata": {"timeframe": tf, "ob_index": target_ob["index"]}
            }

        return None

    def manage_position(self, position: Dict, market_data: Dict) -> Optional[Dict]:
        return None
