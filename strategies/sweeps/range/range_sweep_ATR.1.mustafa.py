"""
1. Summary: Volatility-adjusted range sweep strategy.
2. Description: Tracks price consolidation using rolling ATR volatility bands rather than time-based sessions. Enters positions on sweep-reversals of dynamically calculated ATR boundaries, filtering out over-extended parabolic moves.
3. Context: Relies on ta/patterns/sweep.py and ATR indicators.
"""
import logging
import math
from typing import Dict, Optional, Any, List
from strategies.base_strategy import JBaseStrategy
from tools.trading_utils import calculate_position_size, format_order_quantity, get_price_precision
from ta.indicators.atr import is_expansion_candle
from ta.patterns.structure import identify_structure
from ta.patterns.liquidity import identify_liquidity
from ta.patterns.fvg import detect_fvgs
import config

class RangeSweepATRStrategy(JBaseStrategy):
    def __init__(self, config_overrides: Optional[Dict] = None, simulator=None, model=None):
        super().__init__(
            name="range_sweep_ATR",
            version="1",
            author="mustafa",
            simulator=simulator,
            model=model,
            config_overrides=config_overrides
        )
        self._cache = {} # [PERF-005] Cache for expensive calculations

        # --- Strategy-Specific Parameters ---
        # [TECH-001] bypass_external_filters:
        # If True, the core Engine skips Layer 1 safety checks (Correlation, Cooldown, Regimes).
        # This strategy will still calculate its INTERNAL requirements (ATR Expansion, BOS)
        # regardless of this toggle, as they are mandatory for its logic.
        self.params = {
            "execution_tf": "1m", # Timeframe used for final entry execution and low timeframe structure breaks
            "bypass_external_filters": False, # [TECH-001] Toggle for Layer 1 safety checks
            "range_tf": "4H",
            "atr_multiplier": 5.0,
            "atr_period": 14,
            "max_double_downs": 1,
            "h1_strength": 2,
            "m15_lookback": 50,
            "m15_swing_strength": 2,
            "m1_strength": 2,
            "fvg_depth": 50,
            "tp1_rrr": 1.5,
            "tp2_rrr": 2.5,
            "tp1_qty_ratio": 0.7,
            "max_active_anchors": 5 # Maximum concurrent unswept anchors kept alive
        }

        # [TECH-001] Explicit history requirements for authenticity
        # Values matched to technical module scan depths and catch-up range.
        self.required_history = {"4H": 40, "1H": 120, "15m": 60, self.params["execution_tf"]: 300}

        if config_overrides:
            for k in self.params:
                if k in config_overrides:
                    self.params[k] = config_overrides[k]

    def get_entry_signal(self, market_data: Dict) -> Optional[Dict]:
        symbol = market_data["symbol"]
        exec_tf = self.params.get("execution_tf", "1m")

        range_tf = self.params["range_tf"]
        h4 = self._get_ohlcv(symbol, range_tf)
        h1 = self._get_ohlcv(symbol, "1H")
        m15 = self._get_ohlcv(symbol, "15m")
        m1 = self._get_ohlcv(symbol, exec_tf)

        if not h4 or not h1 or not m15 or not m1: return None

        # --- Phase 1: Expansion Detection [CACHED] ---
        state_key = f"{symbol}_atr_setup_state"
        state = self.get_state(state_key, self.simulator) or "IDLE"

        # [REPAIR-20260708] Cooldown reset to allow multiple trades per expansion
        if state == "COMPLETED":
            last_trigger = self.get_state(f"{symbol}_atr_last_trigger_ts", self.simulator)
            if last_trigger and m1[-1]['ts'] - float(last_trigger) > 3600: # 1 hour cooldown
                self.save_state(state_key, "IDLE", self.simulator)
                state = "IDLE"

        anchors_raw = self.get_state(f"{symbol}_atr_anchors", self.simulator) or []
        anchors = []
        if anchors_raw and anchors_raw != "None":
            try:
                import ast
                if isinstance(anchors_raw, str):
                    anchors = ast.literal_eval(anchors_raw)
                else:
                    anchors = anchors_raw
            except:
                anchors = []

        # Check for NEW expansion candle [CACHED]
        last_h4_ts = h4[-1]['ts']
        cache_key_exp = f"{symbol}_expansion_h4"
        if self._cache.get(cache_key_exp, {}).get('ts') == last_h4_ts:
            expansion = self._cache[cache_key_exp]['expansion']
        else:
            expansion = is_expansion_candle(
                h4,
                multiplier=self.params["atr_multiplier"],
                period=self.params["atr_period"],
                timeframe=range_tf
            )
            self._cache[cache_key_exp] = {'ts': last_h4_ts, 'expansion': expansion}

        if expansion['is_expansion']:
            cand = expansion['candle']
            new_anchor = {
                'high': cand['h'],
                'low': cand['l'],
                'ts': cand['ts'],
                'open': cand.get('o', cand.get('open', cand['h'])),
                'close': cand.get('c', cand.get('close', cand['l']))
            }

            # Enforce Maximum ATR Expansion Cap to filter out extreme exhaustion moves [REPAIR]
            max_cap = getattr(self.simulator.config if self.simulator else config, "MAX_ATR_EXPANSION_MULTIPLIER", 20.0)
            if expansion['ratio'] > max_cap:
                log_rejections = getattr(self.simulator.config if self.simulator else config, "LOG_REJECTIONS", False)
                msg = f"[{symbol}] Discarding expansion anchor: ratio {expansion['ratio']:.1f}x exceeds maximum ATR expansion cap of {max_cap:.1f}x."
                if log_rejections:
                    self.logger.info(msg)
                else:
                    self.logger.debug(msg)
                if state == "WAITING_FOR_SWEEP":
                    # Expired/invalidated
                    self.save_state(state_key, "IDLE", self.simulator)
                    self.save_state(f"{symbol}_atr_anchors", [], self.simulator)
                    state = "IDLE"
                    anchors = []
            else:
                if state in ["IDLE", "WAITING_FOR_SWEEP"]:
                    # Verify if this anchor timestamp is already registered
                    if not any(a['ts'] == cand['ts'] for a in anchors):
                        self.logger.info(f"[{symbol}] Expansion Candle detected ({expansion['ratio']:.1f}x ATR)!")
                        anchors.append(new_anchor)

                        # Enforce maximum concurrent active anchors
                        max_anchors = self.params.get("max_active_anchors", 5)
                        while len(anchors) > max_anchors:
                            anchors.pop(0) # Oldest unswept anchor is replaced

                        self.save_state(f"{symbol}_atr_anchors", anchors, self.simulator)
                        self.save_state(state_key, "WAITING_FOR_SWEEP", self.simulator)
                        state = "WAITING_FOR_SWEEP"
                        self.record_milestone("Phase 1: ATR Expansion Anchor", cand['ts'], range_tf)

        # Check for range expiration
        # If too many 4H candles pass since the anchor without a sweep, reset.
        if state == "WAITING_FOR_SWEEP" and anchors:
            last_closed_h4_ts = h4[-2]['ts'] if len(h4) >= 2 else 0
            # Allow 24 hours (6 candles of 4H) for a sweep to occur
            anchors = [a for a in anchors if last_closed_h4_ts <= a['ts'] + (6 * 14400)]
            self.save_state(f"{symbol}_atr_anchors", anchors, self.simulator)
            if not anchors:
                self.save_state(state_key, "IDLE", self.simulator)
                state = "IDLE"

        # Load our active setup anchor if we are in an active trajectory
        anchor = None
        if state in ["IDLE", "WAITING_FOR_SWEEP"]:
            # During monitoring, we don't have an active setup anchor yet, so we default to the latest one
            anchor = anchors[-1] if anchors else None
        else:
            anchor_raw = self.get_state(f"{symbol}_atr_active_setup_anchor", self.simulator)
            if anchor_raw and anchor_raw != "None":
                try:
                    import ast
                    if isinstance(anchor_raw, str):
                        anchor = ast.literal_eval(anchor_raw)
                    else:
                        anchor = anchor_raw
                except:
                    anchor = None

        if not anchor: return None

        # --- Phase 2: Bias (1H) [CACHED] ---
        last_h1_ts = h1[-1]['ts']
        cache_key = f"{symbol}_bias_1h"
        if self._cache.get(cache_key, {}).get('ts') == last_h1_ts:
            bias = self._cache[cache_key]['bias']
        else:
            h1_struct = identify_structure(h1, strength=self.params["h1_strength"])
            h1_sig = h1_struct.get('structure_signal') or ''

            bias = 'neutral'
            if 'bullish' in h1_sig: bias = 'bullish'
            elif 'bearish' in h1_sig: bias = 'bearish'

            self._cache[cache_key] = {'ts': last_h1_ts, 'bias': bias}

        if bias == 'neutral': return None

        # --- Phase 3: Sweep Detection (15m) ---
        if state == "WAITING_FOR_SWEEP":
            sweep_detected = False
            sweep_side = None
            sweep_ts = 0
            swept_anchor = None

            # Iterate through all active concurrent anchors to detect if any is swept
            for a_cand in anchors:
                for c in m15[-24:]:
                    if bias == 'bullish':
                        if c['l'] < a_cand['low'] and c['c'] > a_cand['low']:
                            sweep_detected = True; sweep_side = 'ssl'; sweep_ts = c['ts']; swept_anchor = a_cand; break
                    else: # bearish
                        if c['h'] > a_cand['high'] and c['c'] < a_cand['high']:
                            sweep_detected = True; sweep_side = 'bsl'; sweep_ts = c['ts']; swept_anchor = a_cand; break
                if sweep_detected:
                    break

            if sweep_detected:
                # Zombie Sweep Prevention
                last_traded_sweep = self.get_state(f"{symbol}_atr_last_traded_sweep_ts", self.simulator)
                if last_traded_sweep is not None and sweep_ts <= float(last_traded_sweep):
                    return None

                # Lock this swept anchor as our active setup anchor
                self.save_state(f"{symbol}_atr_active_setup_anchor", swept_anchor, self.simulator)
                anchor = swept_anchor

                # Remove the swept anchor from the concurrent monitoring pool
                anchors = [a for a in anchors if a['ts'] != swept_anchor['ts']]
                self.save_state(f"{symbol}_atr_anchors", anchors, self.simulator)

                self.record_milestone(f"Phase 2: 1H {bias.upper()} Bias", h1[-1]['ts'], "1H")
                self.record_milestone(f"Phase 3: 15m {sweep_side.upper()} Sweep", sweep_ts, "15m")
                self.logger.info(f"[{symbol}] Sweep of ATR Anchor detected! Catching up sequence.")

                # Check for abandonment
                if m1[-1]['ts'] - sweep_ts > (6 * 3600): # 6 hours limit for ATR range
                    self.save_state(state_key, "ABANDONED", self.simulator)
                    return None

                self.save_state(state_key, "WAITING_FOR_BOS1", self.simulator)
                self.save_state(f"{symbol}_atr_sweep_side", sweep_side, self.simulator)
                self.save_state(f"{symbol}_atr_last_milestone_ts", sweep_ts, self.simulator)
                state = "WAITING_FOR_BOS1"
            else:
                return None

        # --- Phase 4-7: Catch-up & Execution Sequence (1m) ---
        sweep_side = self.get_state(f"{symbol}_atr_sweep_side", self.simulator)
        last_ms_ts = float(self.get_state(f"{symbol}_atr_last_milestone_ts", self.simulator) or 0)

        # Scan history since last milestone
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
                    self.save_state(state_key, "WAITING_FOR_FVG", self.simulator)
                    self.save_state(f"{symbol}_atr_last_milestone_ts", curr_c['ts'], self.simulator)
                    state = "WAITING_FOR_FVG"

            if state == "WAITING_FOR_FVG":
                fvg_data = detect_fvgs(ctx_m1, depth=self.params["fvg_depth"])
                target_fvg = 'bullish' if sweep_side == 'ssl' else 'bearish'
                if fvg_data.get('nearest_fvg_type') == target_fvg:
                    self.record_milestone(f"Phase 5: {exec_tf} FVG Formed", curr_c['ts'], exec_tf)
                    self.save_state(state_key, "WAITING_FOR_RETEST", self.simulator)
                    self.save_state(f"{symbol}_atr_last_milestone_ts", curr_c['ts'], self.simulator)
                    state = "WAITING_FOR_RETEST"

            if state == "WAITING_FOR_RETEST":
                fvg_data = detect_fvgs(ctx_m1, depth=self.params["fvg_depth"])
                target_fvg = 'bullish' if sweep_side == 'ssl' else 'bearish'
                if fvg_data.get('nearest_fvg_type') == target_fvg:
                    self.record_milestone(f"Phase 6: {exec_tf} FVG Retest", curr_c['ts'], exec_tf)
                    self.save_state(state_key, "WAITING_FOR_BOS2", self.simulator)
                    self.save_state(f"{symbol}_atr_last_milestone_ts", curr_c['ts'], self.simulator)
                    state = "WAITING_FOR_BOS2"

            if state == "WAITING_FOR_BOS2":
                break

        # Final trigger check
        if state == "WAITING_FOR_BOS2":
            m1_struct = identify_structure(m1, strength=self.params["m1_strength"])
            m1_sig = m1_struct.get('structure_signal') or ''
            if (sweep_side == 'ssl' and 'bullish' in m1_sig) or (sweep_side == 'bsl' and 'bearish' in m1_sig):
                # EXECUTION
                entry_price = m1[-1]['c']

                # Get asset precision
                price_place, tick_size = get_price_precision(symbol, self.simulator.contract_specs if self.simulator else None)

                # SL: 1 tick past FVG extreme
                fvg_data = detect_fvgs(m1, depth=self.params["fvg_depth"])
                if sweep_side == 'ssl':
                    fvg_extreme = fvg_data.get('nearest_fvg_bottom') or (entry_price * 0.995)
                    stop_price = fvg_extreme - tick_size
                else:
                    fvg_extreme = fvg_data.get('nearest_fvg_top') or (entry_price * 1.005)
                    stop_price = fvg_extreme + tick_size

                # Enforce minimum stop-loss distance guard (at least SL_MOVE to avoid zero-width fee traps)
                min_stop_dist = entry_price * getattr(config, "SL_MOVE", 0.004)
                if abs(entry_price - stop_price) < min_stop_dist:
                    if sweep_side == 'ssl':
                        stop_price = entry_price - min_stop_dist
                    else:
                        stop_price = entry_price + min_stop_dist

                risk = abs(entry_price - stop_price)
                tp1 = entry_price + (risk * self.params["tp1_rrr"] if sweep_side == 'ssl' else -risk * self.params["tp1_rrr"])
                tp2 = entry_price + (risk * self.params["tp2_rrr"] if sweep_side == 'ssl' else -risk * self.params["tp2_rrr"])

                # Refine with Liquidity formed SINCE Expansion [CACHED]
                last_m15_ts = m15[-1]['ts']
                cache_key_liq_anchor = f"{symbol}_liq_15m_{anchor['ts']}"
                if self._cache.get(cache_key_liq_anchor, {}).get('ts') == last_m15_ts:
                    liq_15m = self._cache[cache_key_liq_anchor]['liq']
                else:
                    liq_15m = identify_liquidity(
                        m15,
                        lookback=self.params["m15_lookback"],
                        swing_strength=self.params["m15_swing_strength"],
                        start_ts=anchor['ts']
                    )
                    self._cache[cache_key_liq_anchor] = {'ts': last_m15_ts, 'liq': liq_15m}
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

                # Position Sizing (Compounding Aware)
                equity = market_data.get("equity") or (self.simulator.equity if self.simulator else config.INITIAL_EQUITY)
                starting_equity = getattr(config, 'INITIAL_EQUITY', 15.0)
                reinvest_pct = getattr(config, 'REINVESTMENT_PERCENTAGE', 1.0)

                if equity > starting_equity:
                    riskable_equity = starting_equity + (equity - starting_equity) * reinvest_pct
                else:
                    riskable_equity = equity

                qty = calculate_position_size(riskable_equity, config.RISK_PER_TRADE, entry_price, stop_price)

                # Hardening / Sizing
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

                if self.record_milestone(f"Phase 7: {exec_tf} BOS2 (Entry Trigger)", m1[-1]['ts'], exec_tf):
                    self.logger.info(f"[{symbol}] {sweep_side.upper()} Entry Triggered!")

                self.save_state(state_key, "COMPLETED", self.simulator)
                self.save_state(f"{symbol}_atr_last_trigger_ts", m1[-1]['ts'], self.simulator)

                # Save the active sweep timestamp to prevent Zombie Sweep repeat loops
                active_sweep_ts = self.get_state(f"{symbol}_atr_last_milestone_ts", self.simulator)
                if active_sweep_ts:
                    self.save_state(f"{symbol}_atr_last_traded_sweep_ts", active_sweep_ts, self.simulator)

                tp1_qty = round(qty * self.params["tp1_qty_ratio"], qty_place)

                # Determine whether the range candle was bullish or bearish [REPAIR]
                range_candle_type = "unknown"
                if anchor and "close" in anchor and "open" in anchor:
                    range_candle_type = "bullish" if anchor["close"] >= anchor["open"] else "bearish"

                return {
                    "side": "buy" if sweep_side == 'ssl' else "sell",
                    "entry_price": entry_price,
                    "stop_price": stop_price,
                    "exit_price": tp2,
                    "tp1_price": tp1,
                    "tp1_qty": tp1_qty,
                    "tp2_qty": qty - tp1_qty,
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
            dd_count = int(self.get_state(f"{symbol}_atr_dd_count", self.simulator) or 0)
            if dd_count < self.params["max_double_downs"]:
                self.logger.info(f"DOUBLE DOWN for {symbol} {side}")
                self.save_state(f"{symbol}_atr_dd_count", dd_count + 1, self.simulator)
                return {"action": "double_size"}

        return None
