"""
1. Summary: Killzone session liquidity sweep reversal strategy.
2. Description: Monitors specific London and New York session killzones to identify institutional liquidity sweeps. Captures rapid trend reversals when prices wick past local session extremes and close back inside the range.
3. Context: Relies on ta/patterns/sessions.py and ta/patterns/sweep.py.
"""
import logging
import math
from typing import Dict, Optional, Any, List
from strategies.base_strategy import JBaseStrategy
from tools.trading_utils import calculate_position_size, format_order_quantity, get_price_precision
from ta.patterns.sessions import identify_overnight_range, identify_sessions
from ta.patterns.structure import identify_structure
from ta.patterns.liquidity import identify_liquidity
from ta.patterns.fvg import detect_fvgs
from ta.patterns.swings import detect_swings
from ta.utils import convert_to_local
import config

class KillzoneSweepStrategy(JBaseStrategy):
    def __init__(self, config_overrides: Optional[Dict] = None, simulator=None):
        super().__init__(
            name="killzone_sweep",
            version="1",
            author="mustafa",
            config_overrides=config_overrides
        )
        self.simulator = simulator
        self._cache = {} # [PERF-005] Cache for expensive calculations

        # --- Strategy-Specific Parameters (with overrides) ---
        # [TECH-001] bypass_external_filters:
        # If True, the core Engine skips Layer 1 safety checks (Correlation, Cooldown, Regimes).
        # This strategy will still calculate its INTERNAL requirements (FVG, Structure, Sessions)
        # regardless of this toggle, as they are mandatory for its logic.
        self.params = {
            "execution_tf": "1m", # Timeframe used for final entry execution and low timeframe structure breaks
            "bypass_external_filters": False, # [TECH-001] Toggle for Layer 1 safety checks
            "fvg_penetration_required": False,
            "max_double_downs": 1,
            "h1_strength": 2,
            "m15_lookback": 50,
            "m15_swing_strength": 2,
            "m1_strength": 2,
            "fvg_depth": 50,
            "tp1_rrr": 1.5,
            "tp2_rrr": 2.5,
            "tp1_qty_ratio": 0.7,
            "prior_close_hour": 16,
            "max_active_anchors": 5 # Maximum concurrent unswept anchors kept alive
        }

        # [TECH-001] Explicit history requirements for authenticity
        # Values matched to technical module scan depths and catch-up range.
        self.required_history = {"1H": 120, "15m": 60, self.params["execution_tf"]: 300}

        # Apply parameter overrides from config_overrides if they exist
        if config_overrides:
            for k in self.params:
                if k in config_overrides:
                    self.params[k] = config_overrides[k]
                    self.logger.info(f"STRATEGY | Override {k} = {self.params[k]}")

    def get_entry_signal(self, market_data: Dict) -> Optional[Dict]:
        symbol = market_data["symbol"]
        exec_tf = self.params.get("execution_tf", "1m")

        # We need data for all 3 timeframes
        h1 = self._get_ohlcv(symbol, "1H")
        m15 = self._get_ohlcv(symbol, "15m")
        m1 = self._get_ohlcv(symbol, exec_tf)

        if not h1 or not m15 or not m1:
            return None

        # --- Phase 1: Bias Identification (1H) [CACHED] ---
        last_h1_ts = h1[-1]['ts']
        cache_key = f"{symbol}_bias_1h"
        if self._cache.get(cache_key, {}).get('ts') == last_h1_ts:
            bias = self._cache[cache_key]['bias']
            ov_range = self._cache[cache_key]['ov_range']
        else:
            ov_range = identify_overnight_range(h1, m1[-1]['ts'])
            if not ov_range:
                return None

            self.record_milestone("Phase 1: 1H Overnight Range", h1[-1]['ts'], "1H")

            h1_struct = identify_structure(h1, strength=self.params["h1_strength"])
            h1_sig = h1_struct.get('structure_signal') or ''

            # Bias: bullish if overall range is trending up or bullish BOS
            bias = 'neutral'
            if 'bullish' in h1_sig: bias = 'bullish'
            elif 'bearish' in h1_sig: bias = 'bearish'

            self._cache[cache_key] = {'ts': last_h1_ts, 'bias': bias, 'ov_range': ov_range}

        if bias == 'neutral':
            return None

        self.record_milestone(f"Phase 2: 1H {bias.upper()} Bias", h1[-1]['ts'], "1H")

        # --- State Management ---
        state_key = f"{symbol}_setup_state"
        state = self.get_state(state_key, self.simulator) or "IDLE"

        # Manage dynamic list of up to 5 concurrent overnight range anchors
        ov_ranges_raw = self.get_state(f"{symbol}_ov_ranges", self.simulator) or []
        ov_ranges = []
        if ov_ranges_raw and ov_ranges_raw != "None":
            try:
                import ast
                if isinstance(ov_ranges_raw, str):
                    ov_ranges = ast.literal_eval(ov_ranges_raw)
                else:
                    ov_ranges = ov_ranges_raw
            except:
                ov_ranges = []

        if ov_range and not any(r['ts'] == ov_range['ts'] for r in ov_ranges):
            ov_ranges.append(ov_range)
            max_anchors = self.params.get("max_active_anchors", 5)
            while len(ov_ranges) > max_anchors:
                ov_ranges.pop(0) # Remove oldest unswept overnight range
            self.save_state(f"{symbol}_ov_ranges", ov_ranges, self.simulator)

        # Load active setup range if running in a trajectory
        if state not in ["IDLE", "COMPLETED"]:
            ov_range_raw = self.get_state(f"{symbol}_active_setup_ov_range", self.simulator)
            if ov_range_raw and ov_range_raw != "None":
                try:
                    import ast
                    if isinstance(ov_range_raw, str):
                        ov_range = ast.literal_eval(ov_range_raw)
                    else:
                        ov_range = ov_range_raw
                except:
                    pass

        # [REPAIR-20260708] Cooldown reset to allow multiple trades per session
        if state == "COMPLETED":
            last_trigger = self.get_state(f"{symbol}_last_trigger_ts", self.simulator)
            if last_trigger and m1[-1]['ts'] - float(last_trigger) > 3600: # 1 hour cooldown
                self.save_state(state_key, "IDLE", self.simulator)
                state = "IDLE"

        # Hub & Session Tracking for Reset
        hub = ov_range.get('hub', 'UNKNOWN')
        last_hub = self.get_state(f"{symbol}_last_hub", self.simulator)

        if hub != last_hub:
            self.record_milestone(f"Phase 0: {hub} Session Start", h1[-1]['ts'], "1H")
            self.save_state(f"{symbol}_last_hub", hub, self.simulator)
            self.save_state(state_key, "IDLE", self.simulator)
            state = "IDLE"

        # --- Phase 2: Sweep Detection (15m) [CACHED] ---
        last_m15_ts = m15[-1]['ts']
        cache_key_liq = f"{symbol}_liq_15m"
        if self._cache.get(cache_key_liq, {}).get('ts') == last_m15_ts:
            liq_15m = self._cache[cache_key_liq]['liq']
        else:
            # Expensive structural scan on 15m
            liq_15m = identify_liquidity(m15, lookback=self.params["m15_lookback"], swing_strength=self.params["m15_swing_strength"])
            self._cache[cache_key_liq] = {'ts': last_m15_ts, 'liq': liq_15m}

        if state == "IDLE":
            # [REPAIR-20260708] Scan last 4 hours (16 candles) for a sweep to catch up immediately
            sweep_detected = False
            sweep_side = None
            sweep_ts = 0
            swept_range = None

            # Iterate through all active concurrent overnight range anchors
            for r_cand in ov_ranges:
                for c in m15[-16:]:
                    if bias == 'bullish':
                        if c['l'] < r_cand['overnight_low'] and c['c'] > r_cand['overnight_low']:
                            sweep_detected = True; sweep_side = 'ssl'; sweep_ts = c['ts']; swept_range = r_cand; break
                    else: # bearish
                        if c['h'] > r_cand['overnight_high'] and c['c'] < r_cand['overnight_high']:
                            sweep_detected = True; sweep_side = 'bsl'; sweep_ts = c['ts']; swept_range = r_cand; break
                if sweep_detected:
                    break

            if sweep_detected:
                # Zombie Sweep Prevention
                last_traded_sweep = self.get_state(f"{symbol}_last_traded_sweep_ts", self.simulator)
                if last_traded_sweep is not None and sweep_ts <= float(last_traded_sweep):
                    return None

                # Lock this swept range as our active setup overnight range
                self.save_state(f"{symbol}_active_setup_ov_range", swept_range, self.simulator)
                ov_range = swept_range

                # Remove the swept range from the concurrent monitoring queue
                ov_ranges = [r for r in ov_ranges if r['ts'] != swept_range['ts']]
                self.save_state(f"{symbol}_ov_ranges", ov_ranges, self.simulator)

                if self.record_milestone(f"Phase 3: 15m {sweep_side.upper()} Sweep", sweep_ts, "15m"):
                    self.logger.info(f"[{symbol}] 15m Sweep detected ({sweep_side.upper()})! Catching up sequence.")

                # Check for abandonment (sweep was too long ago)
                if m1[-1]['ts'] - sweep_ts > (4 * 3600): # 4 hours limit
                    self.logger.debug(f"[{symbol}] Sweep abandoned (too old).")
                    self.save_state(state_key, "ABANDONED", self.simulator)
                    return None

                self.save_state(state_key, "WAITING_FOR_BOS1", self.simulator)
                self.save_state(f"{symbol}_sweep_side", sweep_side, self.simulator)
                self.save_state(f"{symbol}_last_milestone_ts", sweep_ts, self.simulator)
                state = "WAITING_FOR_BOS1"
            else:
                return None

        # --- Phase 3: Catch-up & Execution Sequence (1m) ---
        sweep_side = self.get_state(f"{symbol}_sweep_side", self.simulator)
        last_ms_ts = float(self.get_state(f"{symbol}_last_milestone_ts", self.simulator) or 0)

        # Scan history since last milestone to catch up to the current state
        # Limit scan to last 100 1m candles for performance
        relevant_m1_indices = [i for i, c in enumerate(m1) if c['ts'] > last_ms_ts]
        if len(relevant_m1_indices) > 100: relevant_m1_indices = relevant_m1_indices[-100:]

        for idx in relevant_m1_indices:
            ctx_m1 = m1[:idx+1]
            curr_c = ctx_m1[-1]

            if state == "WAITING_FOR_BOS1":
                m1_struct = identify_structure(ctx_m1, strength=self.params["m1_strength"])
                m1_sig = m1_struct.get('structure_signal') or ''
                if (sweep_side == 'ssl' and 'bullish' in m1_sig) or (sweep_side == 'bsl' and 'bearish' in m1_sig):
                    self.record_milestone(f"Phase 4: {exec_tf} BOS1", curr_c['ts'], exec_tf)
                    self.logger.info(f"[{symbol}] {exec_tf} BOS1 detected in history! Entering WAITING_FOR_FVG")
                    self.save_state(state_key, "WAITING_FOR_FVG", self.simulator)
                    self.save_state(f"{symbol}_last_milestone_ts", curr_c['ts'], self.simulator)
                    state = "WAITING_FOR_FVG"

            if state == "WAITING_FOR_FVG":
                fvg_data = detect_fvgs(ctx_m1, depth=self.params["fvg_depth"])
                target_fvg = 'bullish' if sweep_side == 'ssl' else 'bearish'
                if fvg_data.get('nearest_fvg_type') == target_fvg:
                    self.record_milestone(f"Phase 5: {exec_tf} FVG Formed", curr_c['ts'], exec_tf)
                    self.logger.info(f"[{symbol}] {exec_tf} FVG detected in history! Entering WAITING_FOR_RETEST")
                    self.save_state(state_key, "WAITING_FOR_RETEST", self.simulator)
                    self.save_state(f"{symbol}_last_milestone_ts", curr_c['ts'], self.simulator)
                    state = "WAITING_FOR_RETEST"

            if state == "WAITING_FOR_RETEST":
                fvg_data = detect_fvgs(ctx_m1, depth=self.params["fvg_depth"])
                target_fvg = 'bullish' if sweep_side == 'ssl' else 'bearish'
                if fvg_data.get('nearest_fvg_type') == target_fvg:
                    self.record_milestone(f"Phase 6: {exec_tf} FVG Retest", curr_c['ts'], exec_tf)
                    self.logger.info(f"[{symbol}] {exec_tf} FVG Retest complete in history! Entering WAITING_FOR_BOS2")
                    self.save_state(state_key, "WAITING_FOR_BOS2", self.simulator)
                    self.save_state(f"{symbol}_last_milestone_ts", curr_c['ts'], self.simulator)
                    state = "WAITING_FOR_BOS2"

            if state == "WAITING_FOR_BOS2":
                break

        # Final check for entry trigger (must be fresh/current)
        if state == "WAITING_FOR_BOS2":
            m1_struct = identify_structure(m1, strength=self.params["m1_strength"])
            m1_sig = m1_struct.get('structure_signal') or ''

            if (sweep_side == 'ssl' and 'bullish' in m1_sig) or (sweep_side == 'bsl' and 'bearish' in m1_sig):
                # --- Phase 4: Entry & Risk Management ---
                entry_price = m1[-1]['c']

                # Get asset precision
                price_place, tick_size = get_price_precision(symbol, self.simulator.contract_specs if self.simulator else None)

                # SL: exactly 1 tick past FVG extreme (opposite side)
                fvg_data = detect_fvgs(m1, depth=self.params["fvg_depth"])
                if sweep_side == 'ssl': # Bullish Entry
                    # SL is below FVG Bottom
                    fvg_extreme = fvg_data.get('nearest_fvg_bottom') or (entry_price * 0.995)
                    stop_price = fvg_extreme - tick_size
                else: # Bearish Entry
                    # SL is above FVG Top
                    fvg_extreme = fvg_data.get('nearest_fvg_top') or (entry_price * 1.005)
                    stop_price = fvg_extreme + tick_size

                # Enforce minimum stop-loss distance guard (at least SL_MOVE to avoid zero-width fee traps)
                min_stop_dist = entry_price * getattr(config, "SL_MOVE", 0.004)
                if abs(entry_price - stop_price) < min_stop_dist:
                    if sweep_side == 'ssl':
                        stop_price = entry_price - min_stop_dist
                    else:
                        stop_price = entry_price + min_stop_dist

                # TP1/TP2 from 15m liquidity
                risk = abs(entry_price - stop_price)
                min_tp1_dist = risk * self.params["tp1_rrr"]
                min_tp2_dist = risk * self.params["tp2_rrr"]

                tp1 = entry_price + (min_tp1_dist if sweep_side == 'ssl' else -min_tp1_dist)
                tp2 = entry_price + (min_tp2_dist if sweep_side == 'ssl' else -min_tp2_dist)

                # Refine with actual liquidity levels
                if sweep_side == 'ssl':
                    for level in liq_15m.get('all_bsl', []):
                        if level >= tp1: tp1 = level; break
                    for level in liq_15m.get('all_bsl', []):
                        if level >= tp2: tp2 = level; break
                else:
                    for level in liq_15m.get('all_ssl', []):
                        if level <= tp1: tp1 = level; break
                    for level in liq_15m.get('all_ssl', []):
                        if level <= tp2: tp2 = level; break

                # Calculate Quantity based on risk and reinvestment settings
                equity = market_data.get("equity") or (self.simulator.equity if self.simulator else config.INITIAL_EQUITY)
                starting_equity = getattr(config, 'INITIAL_EQUITY', 15.0)
                reinvest_pct = getattr(config, 'REINVESTMENT_PERCENTAGE', 1.0)

                if equity > starting_equity:
                    riskable_equity = starting_equity + (equity - starting_equity) * reinvest_pct
                else:
                    riskable_equity = equity

                qty = calculate_position_size(riskable_equity, config.RISK_PER_TRADE, entry_price, stop_price)

                # Round quantity based on asset specs
                qty, qty_place = format_order_quantity(
                    qty,
                    entry_price,
                    equity,
                    self.simulator.contract_specs if self.simulator else None,
                    symbol,
                    logger=self.logger
                )
                if qty is None:
                    return None

                # TRIGGER ENTRY & LOG DATA
                if self.record_milestone(f"Phase 7: {exec_tf} BOS2 (Entry Trigger)", m1[-1]['ts'], exec_tf):
                    self.logger.info(f"[{symbol}] {sweep_side.upper()} BOS2 Triggered ({m1_sig})! Hub: {hub}")
                    self.logger.info(f"  - Entry: {entry_price:.8f}")
                    self.logger.info(f"  - SL   : {stop_price:.8f} (Risk: {risk:.8f})")
                    self.logger.info(f"  - TP1  : {tp1:.8f} | TP2: {tp2:.8f}")
                    self.logger.info(f"  - Qty  : {qty:.3f} (Equity: {equity:.2f})")

                self.save_state(state_key, "COMPLETED", self.simulator)
                self.save_state(f"{symbol}_last_trigger_ts", m1[-1]['ts'], self.simulator)

                # Save the active sweep timestamp to prevent Zombie Sweep repeat loops
                active_sweep_ts = self.get_state(f"{symbol}_last_milestone_ts", self.simulator)
                if active_sweep_ts:
                    self.save_state(f"{symbol}_last_traded_sweep_ts", active_sweep_ts, self.simulator)

                tp1_qty = qty * self.params["tp1_qty_ratio"]
                # Ensure tp1_qty also follows asset precision and is at least one tick
                min_qty_tick = 1 / (10**qty_place)
                if tp1_qty < min_qty_tick:
                    tp1_qty = 0 # Disable split if too small
                else:
                    tp1_qty = round(tp1_qty, qty_place)

                tp2_qty = qty - tp1_qty

                # Determine whether the range candle was bullish or bearish [REPAIR]
                range_candle_type = "unknown"
                if ov_range and "close" in ov_range and "open" in ov_range:
                    if ov_range["close"] is not None and ov_range["open"] is not None:
                        range_candle_type = "bullish" if ov_range["close"] >= ov_range["open"] else "bearish"

                return {
                    "side": "buy" if sweep_side == 'ssl' else "sell",
                    "entry_price": entry_price,
                    "stop_price": stop_price,
                    "exit_price": tp2,
                    "tp1_price": tp1,
                    "tp1_qty_ratio": self.params["tp1_qty_ratio"],
                    "tp1_qty": tp1_qty,
                    "tp2_qty": tp2_qty,
                    "qty": qty,
                    "range_candle_type": range_candle_type,
                    "bypass_global_filters": self.params["bypass_external_filters"] # [TECH-001] Pass toggle
                }

        return None

    def manage_position(self, position: Dict, market_data: Dict) -> Optional[Dict]:
        """
        Implements TP1 50% exit and Double-Down logic.
        """
        symbol = market_data["symbol"]
        exec_tf = self.params.get("execution_tf", "1m")
        m1 = self._get_ohlcv(symbol, exec_tf)
        if not m1: return None

        # 1. TP1 logic is already handled by engine (BE+TP1+TP2)
        # but we can add the 50% logic here if needed.

        # 2. Scaling (Double-Down)
        # 17. if there is an engulfing retracement candle... closing short of entry price, double size.
        entry_price = position['entry']
        side = position['side']

        last_c = m1[-1]
        prev_c = m1[-2]

        is_retracement = False
        if side == 'buy' and last_c['c'] < entry_price:
            # Engulfing bearish retracement?
            if last_c['c'] < prev_c['l'] and last_c['o'] > prev_c['h']:
                is_retracement = True
        elif side == 'sell' and last_c['c'] > entry_price:
            # Engulfing bullish retracement?
            if last_c['c'] > prev_c['h'] and last_c['o'] < prev_c['l']:
                is_retracement = True

        if is_retracement:
            dd_count = int(self.get_state(f"{symbol}_dd_count", self.simulator) or 0)
            if dd_count < self.params["max_double_downs"]:
                self.logger.info(f"DOUBLE DOWN for {symbol} {side}")
                self.save_state(f"{symbol}_dd_count", dd_count + 1, self.simulator)
                # Return update signal to double size
                # In this foundation, we'll return a 'double' command
                return {"action": "double_size"}

        return None
