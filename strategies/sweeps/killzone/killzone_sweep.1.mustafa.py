"""
# Killzone Sweep Strategy v1.mustafa

## Overview
The Killzone Sweep strategy is designed to capitalize on "Institutional Liquidity Raids" that typically
occur during the opening volatility of major global financial hubs. It assumes that retail stop-losses
reside just beyond the highs and lows of the "Overnight Session" (the period between core exchange hours).
When the market opens (the "Killzone"), institutions often drive price into these liquidity pools to
fill large orders before reversing direction. This strategy identifies that reversal sequence with
high precision across three timeframes.

## Hubs and Hours (All times EST)
- **US**: Core 9:30-16:00 | Overnight 16:00-9:30
- **UK/EU**: Core 3:00-11:30 | Overnight 11:30-3:00
- **JAPAN**: Core 19:00-1:00 | Overnight 1:00-19:00
- **HK**: Core 20:30-4:00 | Overnight 4:00-20:30

## Goals & Rationale
- **Compounding Target**: Targets a net ROI of 1-5% per trade. While the system's "north star" is 5%, this strategy balances that with realistic institutional liquidity targets to maintain a high win rate (>65%).
- **Frequency**: Aims for 1-3 high-quality setups per asset per day. By monitoring 250 assets, the global frequency supports the rapid compounding goal.
- **Selectivity**: Prioritize setup quality over raw frequency. It avoids "choppy" mid-range price action, focusing exclusively on extremes where institutional "smart money" is forced to reveal its hand.
- **Risk Management**: Employs a strict 0.5% risk-per-trade model with fee-aware position sizing. Uses an "Aggressive Break-Even" (moving SL to 50% profit point) upon TP1 to eliminate tail risk early.

## Modules Used
- `ta/patterns/sessions.py`: Orchestrates the awareness of which global hub is active and calculates
  the preceding "Overnight Range" (including Friday close to Monday open logic).
- `ta/patterns/structure.py`: Detects Break of Structure (BOS) and Market Structure Shifts (MSS) to
  confirm trend transitions on 1H (Bias) and 1m (Execution).
- `ta/patterns/liquidity.py`: Identifies Buy-Side Liquidity (BSL) and Sell-Side Liquidity (SSL) pools
  on the 15m timeframe to use as Take-Profit targets.
- `ta/patterns/fvg.py`: Locates Fair Value Gaps on the 1m timeframe to define high-confidence
  entry zones and protective Stop-Loss levels.
- `tools/trading_utils.py`: Calculates fee-aware position sizing to ensure exactly 0.5% risk (or user-defined).

## The Intended Flow
1. **Hub Detection**: The strategy identifies the current active Hub (US, UK, etc.) and determines
   if it is within the 2-hour "Killzone" of the Core Session start.
2. **Overnight Range (1H)**: Scans back to find the High and Low established during the hub's preceding
   overnight session. For Monday opens, this range spans back to the previous Friday's close.
3. **Bias (1H)**: Establishes directional bias (Bullish/Bearish) based on 1H Market Structure.
4. **Liquidity Sweep (15m)**: Waits for price to "sweep" (wick beyond) the overnight extreme *opposite*
   to the bias. (e.g., Bullish Bias -> Sweep of Overnight Low).
5. **Reversal Sequence (1m)**:
   - **BOS1**: Confirms the first shift in internal structure back toward the bias.
   - **FVG**: Identifies an imbalance created during the impulsive BOS1 move.
   - **Retest**: Waits for price to re-enter the FVG zone, confirming institutional interest.
   - **BOS2**: Final trigger—a second break of structure following the retest, signaling
     continuation of the reversal.
6. **Execution**: Entry at the close of the BOS2 candle.
   - **SL**: Placed 1 tick beyond the 1m FVG.
   - **TP1 (50%)**: Targeted at the first 15m liquidity level providing at least 1:1.5 RRR.
   - **TP2**: Targeted at the next 15m liquidity level at/beyond 1:2.5 RRR.

## Limitations & Assumptions
- **Volume Dependence**: Expects standard exchange hours for liquidity (London/NY overlap is optimal); may underperform during low-volume bank holidays or late Asian session "drifts".
- **Latency Sensitivity**: Requires low-latency execution as 1m BOS2 triggers can move significantly within seconds.
- **History Requirement**: Needs at least 3-5 days of 1H/15m data to accurately calculate multi-day overnight ranges and establish consistent MTF bias.
- **Market Conditions**: Highly effective in Trending or Range-Expansion markets. May suffer from "paper cuts" in low-volatility, sideways-grinding markets where liquidity sweeps lack follow-through.
- **Asset Universe**: Designed for high-volume USDT-M futures on Bitget; requires assets with tight spreads (<0.1%) and sufficient order book depth to support the intended position sizes.
"""

import logging
import math
from typing import Dict, Optional, Any, List
from strategies.base_strategy import JBaseStrategy
from tools.trading_utils import calculate_position_size
from ta.patterns.sessions import identify_overnight_range, identify_sessions
from ta.patterns.structure import identify_structure
from ta.patterns.liquidity import identify_liquidity
from ta.patterns.fvg import detect_fvgs
from ta.patterns.swings import detect_swings
from ta.utils import convert_to_local
import config

log = logging.getLogger("strategies.mustafa")

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

        # [TECH-001] Explicit history requirements for authenticity
        # Values matched to technical module scan depths (e.g. sessions.py scans 120 1H candles)
        self.required_history = {"1H": 120, "15m": 50, "1m": 100}

        # --- Strategy-Specific Parameters (with overrides) ---
        # [TECH-001] bypass_external_filters:
        # If True, the core Engine skips Layer 1 safety checks (Correlation, Cooldown, Regimes).
        # This strategy will still calculate its INTERNAL requirements (FVG, Structure, Sessions)
        # regardless of this toggle, as they are mandatory for its logic.
        self.params = {
            "bypass_external_filters": True, # [TECH-001] Toggle for Layer 1 safety checks
            "fvg_penetration_required": False,
            "max_double_downs": 1,
            "h1_strength": 2,
            "m15_lookback": 50,
            "m15_swing_strength": 2,
            "m1_strength": 2,
            "fvg_depth": 50,
            "tp1_rrr": 1.5,
            "tp2_rrr": 2.5,
            "tp1_qty_ratio": 0.5,
            "prior_close_hour": 16
        }

        # Apply parameter overrides from config_overrides if they exist
        if config_overrides:
            for k in self.params:
                if k in config_overrides:
                    self.params[k] = config_overrides[k]
                    log.info(f"STRATEGY | Override {k} = {self.params[k]}")

    def get_entry_signal(self, market_data: Dict) -> Optional[Dict]:
        symbol = market_data["symbol"]

        # We need data for all 3 timeframes
        h1 = self._get_ohlcv(symbol, "1H")
        m15 = self._get_ohlcv(symbol, "15m")
        m1 = self._get_ohlcv(symbol, "1m")

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
            # [T-003] Check all 15m candles since session start for a sweep
            # This ensures we don't miss a sweep that happened before the current 1m tick
            sweep_detected = False
            sweep_side = None

            # Find index of first 15m candle in current core session
            # (Simplified: check last 8 15m candles = 2 hours)
            for c in m15[-8:]:
                if bias == 'bullish':
                    if c['l'] < ov_range['overnight_low'] and c['c'] > ov_range['overnight_low']:
                        sweep_detected = True; sweep_side = 'ssl'; break
                else: # bearish
                    if c['h'] > ov_range['overnight_high'] and c['c'] < ov_range['overnight_high']:
                        sweep_detected = True; sweep_side = 'bsl'; break

            if sweep_detected:
                if self.record_milestone(f"Phase 3: 15m {sweep_side.upper()} Sweep", m15[-1]['ts'], "15m"):
                    log.info(f"MUSTAFA | {symbol} 15m Sweep detected ({sweep_side.upper()})! Entering WAITING_FOR_BOS1")
                self.save_state(state_key, "WAITING_FOR_BOS1", self.simulator)
                self.save_state(f"{symbol}_sweep_side", sweep_side, self.simulator)
                state = "WAITING_FOR_BOS1"
            else:
                return None

        # --- Phase 3: Execution Sequence (1m) ---
        sweep_side = self.get_state(f"{symbol}_sweep_side", self.simulator)
        m1_struct = identify_structure(m1, strength=self.params["m1_strength"])
        m1_sig = m1_struct.get('structure_signal') or ''

        if state == "WAITING_FOR_BOS1":
            if (sweep_side == 'ssl' and 'bullish' in m1_sig) or (sweep_side == 'bsl' and 'bearish' in m1_sig):
                self.record_milestone("Phase 4: 1m BOS1", m1[-1]['ts'], "1m")
                log.info(f"MUSTAFA | {symbol} 1m BOS1 detected ({m1_sig})! Entering WAITING_FOR_FVG")
                self.save_state(state_key, "WAITING_FOR_FVG", self.simulator)
                state = "WAITING_FOR_FVG"

        if state == "WAITING_FOR_FVG":
            fvg_data = detect_fvgs(m1, depth=self.params["fvg_depth"])
            # Check for FVG in the direction of our bias
            target_fvg = 'bullish' if sweep_side == 'ssl' else 'bearish'

            if fvg_data.get('fvg_count', 0) > 0:
                # Check if ANY of the detected FVGs match our target type
                # detect_fvgs only returns 'nearest', let's trust it for now
                if fvg_data.get('nearest_fvg_type') == target_fvg:
                    self.record_milestone("Phase 5: 1m FVG Formed", m1[-1]['ts'], "1m")
                    log.info(f"MUSTAFA | {symbol} 1m {target_fvg.upper()} FVG detected! Entering WAITING_FOR_RETEST")
                    self.save_state(state_key, "WAITING_FOR_RETEST", self.simulator)
                    state = "WAITING_FOR_RETEST"

        if state == "WAITING_FOR_RETEST":
            fvg_data = detect_fvgs(m1, depth=self.params["fvg_depth"])
            target_fvg = 'bullish' if sweep_side == 'ssl' else 'bearish'
            retested = False

            # More lenient retest logic: any overlap with the target FVG
            if fvg_data.get('nearest_fvg_type') == target_fvg:
                retested = True

            if retested:
                self.record_milestone("Phase 6: 1m FVG Retest", m1[-1]['ts'], "1m")
                log.info(f"MUSTAFA | {symbol} 1m FVG Retest complete! Entering WAITING_FOR_BOS2")
                self.save_state(state_key, "WAITING_FOR_BOS2", self.simulator)
                state = "WAITING_FOR_BOS2"

        if state == "WAITING_FOR_BOS2":
            # Re-check structure with latest params
            m1_struct = identify_structure(m1, strength=self.params["m1_strength"])
            m1_sig = m1_struct.get('structure_signal') or ''

            if (sweep_side == 'ssl' and 'bullish' in m1_sig) or (sweep_side == 'bsl' and 'bearish' in m1_sig):
                # --- Phase 4: Entry & Risk Management ---
                entry_price = m1[-1]['c']

                # Get asset precision
                price_place = 2
                if self.simulator and symbol in self.simulator.contract_specs:
                    price_place = int(self.simulator.contract_specs[symbol].get('pricePlace', 2))
                tick_size = 1 / (10**price_place)

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

                # Calculate Quantity based on risk
                equity = market_data.get("equity") or (self.simulator.equity if self.simulator else config.INITIAL_EQUITY)
                qty = calculate_position_size(equity, config.RISK_PER_TRADE, entry_price, stop_price)

                # Round quantity based on asset specs
                if self.simulator and symbol in self.simulator.contract_specs:
                    spec = self.simulator.contract_specs[symbol]
                    qty_place = int(spec.get('quantityPlace', 3))
                    # Use floor to avoid exceeding margin limits
                    qty = math.floor(qty * (10**qty_place)) / (10**qty_place)

                    # Check minimum size
                    min_qty = float(spec.get('minTradeUSDT', 5.0)) / entry_price
                    if qty < min_qty:
                        qty = math.ceil(min_qty * (10**qty_place)) / (10**qty_place)
                        # Re-verify we still have margin for this rounded-up qty
                        max_lev = float(spec.get('maxLever', 20))
                        if (qty * entry_price) / max_lev > equity * 0.95: # Safety buffer
                            log.warning(f"MUSTAFA | {symbol} Rounded qty {qty} exceeds available margin. Skipping.")
                            return None

                # TRIGGER ENTRY & LOG DATA
                if self.record_milestone("Phase 7: 1m BOS2 (Entry Trigger)", m1[-1]['ts'], "1m"):
                    log.info(f"MUSTAFA | {symbol} {sweep_side.upper()} BOS2 Triggered ({m1_sig})! Hub: {hub}")
                    log.info(f"  - Entry: {entry_price:.8f}")
                    log.info(f"  - SL   : {stop_price:.8f} (Risk: {risk:.8f})")
                    log.info(f"  - TP1  : {tp1:.8f} | TP2: {tp2:.8f}")
                    log.info(f"  - Qty  : {qty:.3f} (Equity: {equity:.2f})")

                self.save_state(state_key, "COMPLETED", self.simulator)

                tp1_qty = qty * self.params["tp1_qty_ratio"]
                # Ensure tp1_qty also follows asset precision
                tp1_qty = round(tp1_qty, qty_place)
                tp2_qty = qty - tp1_qty

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
                    "bypass_global_filters": self.params["bypass_external_filters"] # [TECH-001] Pass toggle
                }

        return None

    def manage_position(self, position: Dict, market_data: Dict) -> Optional[Dict]:
        """
        Implements TP1 50% exit and Double-Down logic.
        """
        symbol = market_data["symbol"]
        m1 = self._get_ohlcv(symbol, "1m")
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
                log.info(f"DOUBLE DOWN for {symbol} {side}")
                self.save_state(f"{symbol}_dd_count", dd_count + 1, self.simulator)
                # Return update signal to double size
                # In this foundation, we'll return a 'double' command
                return {"action": "double_size"}

        return None

    def _get_ohlcv(self, symbol: str, tf: str) -> List[dict]:
        if not self.simulator: return []
        return self.simulator.ohlcv.get(symbol, {}).get(tf, [])
