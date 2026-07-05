"""
# Killzone Sweep Overnight Strategy v1.mustafa

## Overview
The Killzone Sweep Overnight strategy is the inverse of the standard Killzone strategy.
While the standard strategy uses the "Overnight Range" to trade the Core session's volatility,
this strategy uses the preceding "Core Session Range" (the main trading day) to identify
liquidity sweeps during the quieter overnight hours. It assumes that major day highs and
lows act as magnets for price during the overnight session as institutional algos
clear out remaining retail orders before the next day's open.

## Hubs and Hours (All times EST)
- **US**: Core 9:30-16:00 | Overnight 16:00-9:30
- **UK/EU**: Core 3:00-11:30 | Overnight 11:30-3:00
- **JAPAN**: Core 19:00-1:00 | Overnight 1:00-19:00
- **HK**: Core 20:30-4:00 | Overnight 4:00-20:30

## Goals & Rationale
- **Compounding Target**: Targets a net ROI of 1-3% per trade. Overnight sessions typically
  have lower volatility, so profit targets are adjusted to be more realistic for these conditions.
- **Frequency**: 1-2 high-probability setups per asset during the overnight period.
- **Selectivity**: Focuses on "Mean Reversion to the Day Range". It looks for fake-outs
  beyond the day's extremes.
- **Risk Management**: 0.5% risk-per-trade. Uses Aggressive Break-Even (moving SL to 50%
  profit point) upon TP1 to lock in gains during potentially lower-volume periods.

## Modules Used
- `ta/patterns/sessions.py`: Identifies the current active Overnight session and
  retrieves the range of the immediately preceding Core Session (Day Range).
- `ta/patterns/structure.py`: Detects BOS/MSS on 1H (Bias) and 1m (Execution).
- `ta/patterns/liquidity.py`: Identifies liquidity pools established during the day
  to use as targets.
- `ta/patterns/fvg.py`: Defines entry zones and SL placement on the 1m timeframe.
- `tools/trading_utils.py`: Fee-aware position sizing.

## The Intended Flow
1. **Overnight Hub Detection**: Strategy identifies if it is currently in an Overnight
   session for a major hub.
2. **Day Range (1H)**: Retrieves the High and Low established during that same hub's
   immediately preceding main trading day (Core Session).
3. **Bias (1H)**: Directional bias (Bullish/Bearish) from 1H structure.
4. **Liquidity Sweep (15m)**: Waits for price to "sweep" a Day Range extreme during
   the overnight session. (e.g., Bearish Bias -> Sweep of Day High).
5. **Reversal Sequence (1m)**:
   - **BOS1**: Internal structure shift back toward the bias.
   - **FVG**: Imbalance creation.
   - **Retest**: Validation of the imbalance.
   - **BOS2**: Final execution trigger.
6. **Execution**: Entry at BOS2 close.
   - **SL**: 1 tick beyond the FVG extreme.
   - **TP1 (50%)**: First 15m liquidity level from the day session (1:1.2+ RRR).
   - **TP2**: Next 15m liquidity level (1:2.0+ RRR).

## Limitations & Assumptions
- **Volume Sensitivity**: Overnight markets can be thin; requires assets with high 24/7
  liquidity to ensure fills with minimal slippage.
- **Weekend Persistence**: On Friday nights and through the weekend, the Friday Day Range
  is used as the anchor until Monday morning.
- **Lower Volatility**: Expectations for "parabolic" follow-through are lower than during
  the main day session.
"""

import logging
import math
from typing import Dict, Optional, Any, List
from strategies.base_strategy import JBaseStrategy
from tools.trading_utils import calculate_position_size
from ta.patterns.sessions import identify_core_range
from ta.patterns.structure import identify_structure
from ta.patterns.liquidity import identify_liquidity
from ta.patterns.fvg import detect_fvgs
import config

log = logging.getLogger("strategies.mustafa_ov")

class KillzoneSweepOvernightStrategy(JBaseStrategy):
    def __init__(self, config_overrides: Optional[Dict] = None, simulator=None):
        super().__init__(
            name="killzone_sweep_overnight",
            version="1",
            author="mustafa",
            config_overrides=config_overrides
        )
        self.simulator = simulator
        self._cache = {} # [PERF-005] Cache for expensive calculations

        # [TECH-001] Explicit history requirements for authenticity
        # Values matched to technical module scan depths (e.g. sessions.py scans 120 1H candles)
        self.required_history = {"1H": 120, "15m": 100, "1m": 100}

        # --- Strategy-Specific Parameters ---
        # [TECH-001] bypass_external_filters:
        # If True, the core Engine skips Layer 1 safety checks (Correlation, Cooldown, Regimes).
        # This strategy will still calculate its INTERNAL requirements (Structure, Day Range)
        # regardless of this toggle, as they are mandatory for its logic.
        self.params = {
            "bypass_external_filters": True, # [TECH-001] Toggle for Layer 1 safety checks
            "h1_strength": 2,
            "m15_lookback": 100, # More lookback to capture day liquidity
            "m15_swing_strength": 2,
            "m1_strength": 2,
            "fvg_depth": 50,
            "tp1_rrr": 1.2, # Lower targets for overnight
            "tp2_rrr": 2.0,
            "tp1_qty_ratio": 0.5
        }

        if config_overrides:
            for k in self.params:
                if k in config_overrides:
                    self.params[k] = config_overrides[k]

    def get_entry_signal(self, market_data: Dict) -> Optional[Dict]:
        symbol = market_data["symbol"]

        h1 = self._get_ohlcv(symbol, "1H")
        m15 = self._get_ohlcv(symbol, "15m")
        m1 = self._get_ohlcv(symbol, "1m")

        if not h1 or not m15 or not m1: return None

        # --- Phase 1: Preceding Day Range (Core) [CACHED] ---
        last_h1_ts = h1[-1]['ts']
        cache_key = f"{symbol}_bias_1h"
        if self._cache.get(cache_key, {}).get('ts') == last_h1_ts:
            bias = self._cache[cache_key]['bias']
            day_range = self._cache[cache_key]['day_range']
        else:
            day_range = identify_core_range(h1, m1[-1]['ts'])
            if not day_range: return None

            self.record_milestone("Phase 1: Preceding Day Range Found", h1[-1]['ts'], "1H")

            # --- Phase 2: Bias Identification (1H) ---
            h1_struct = identify_structure(h1, strength=self.params["h1_strength"])
            h1_sig = h1_struct.get('structure_signal') or ''

            bias = 'neutral'
            if 'bullish' in h1_sig: bias = 'bullish'
            elif 'bearish' in h1_sig: bias = 'bearish'

            self._cache[cache_key] = {'ts': last_h1_ts, 'bias': bias, 'day_range': day_range}

        if bias == 'neutral': return None

        self.record_milestone(f"Phase 2: 1H {bias.upper()} Bias", h1[-1]['ts'], "1H")

        # --- State Management ---
        state_key = f"{symbol}_ov_setup_state"
        state = self.get_state(state_key, self.simulator) or "IDLE"

        hub = day_range.get('hub', 'UNKNOWN')
        last_hub = self.get_state(f"{symbol}_ov_last_hub", self.simulator)

        if hub != last_hub:
            self.record_milestone(f"Phase 0: {hub} Overnight Start", h1[-1]['ts'], "1H")
            self.save_state(f"{symbol}_ov_last_hub", hub, self.simulator)
            self.save_state(state_key, "IDLE", self.simulator)
            state = "IDLE"

        # --- Phase 3: Day Extreme Sweep (15m) [CACHED] ---
        last_m15_ts = m15[-1]['ts']
        cache_key_liq = f"{symbol}_liq_15m"
        if self._cache.get(cache_key_liq, {}).get('ts') == last_m15_ts:
            liq_15m = self._cache[cache_key_liq]['liq']
        else:
            # We don't necessarily use liq_15m in IDLE state for sweep detection,
            # but we use it later for TP targets. Let's cache it anyway.
            # (Note: identify_liquidity with hub_filter=hub is what we use later)
            liq_15m = None

        if state == "IDLE":
            sweep_detected = False
            sweep_side = None

            # Check for sweep of day range extremes during this overnight session
            # (Last 4-8 hours = 16-32 15m candles)
            for c in m15[-32:]:
                if bias == 'bullish':
                    if c['l'] < day_range['core_low'] and c['c'] > day_range['core_low']:
                        sweep_detected = True; sweep_side = 'ssl'; break
                else: # bearish
                    if c['h'] > day_range['core_high'] and c['c'] < day_range['core_high']:
                        sweep_detected = True; sweep_side = 'bsl'; break

            if sweep_detected:
                if self.record_milestone(f"Phase 3: Day {sweep_side.upper()} Sweep", m15[-1]['ts'], "15m"):
                    log.info(f"MUSTAFA_OV | {symbol} Overnight Sweep of Day {sweep_side.upper()} detected!")
                self.save_state(state_key, "WAITING_FOR_BOS1", self.simulator)
                self.save_state(f"{symbol}_ov_sweep_side", sweep_side, self.simulator)
                state = "WAITING_FOR_BOS1"
            else:
                return None

        # --- Phase 4: Reversal Execution (1m) ---
        sweep_side = self.get_state(f"{symbol}_ov_sweep_side", self.simulator)
        m1_struct = identify_structure(m1, strength=self.params["m1_strength"])
        m1_sig = m1_struct.get('structure_signal') or ''

        if state == "WAITING_FOR_BOS1":
            if (sweep_side == 'ssl' and 'bullish' in m1_sig) or (sweep_side == 'bsl' and 'bearish' in m1_sig):
                self.record_milestone("Phase 4: 1m BOS1", m1[-1]['ts'], "1m")
                self.save_state(state_key, "WAITING_FOR_FVG", self.simulator)
                state = "WAITING_FOR_FVG"

        if state == "WAITING_FOR_FVG":
            fvg_data = detect_fvgs(m1, depth=self.params["fvg_depth"])
            target_fvg = 'bullish' if sweep_side == 'ssl' else 'bearish'
            if fvg_data.get('nearest_fvg_type') == target_fvg:
                self.record_milestone("Phase 5: 1m FVG Formed", m1[-1]['ts'], "1m")
                self.save_state(state_key, "WAITING_FOR_RETEST", self.simulator)
                state = "WAITING_FOR_RETEST"

        if state == "WAITING_FOR_RETEST":
            fvg_data = detect_fvgs(m1, depth=self.params["fvg_depth"])
            target_fvg = 'bullish' if sweep_side == 'ssl' else 'bearish'
            if fvg_data.get('nearest_fvg_type') == target_fvg:
                self.record_milestone("Phase 6: 1m FVG Retest", m1[-1]['ts'], "1m")
                self.save_state(state_key, "WAITING_FOR_BOS2", self.simulator)
                state = "WAITING_FOR_BOS2"

        if state == "WAITING_FOR_BOS2":
            m1_struct = identify_structure(m1, strength=self.params["m1_strength"])
            m1_sig = m1_struct.get('structure_signal') or ''

            if (sweep_side == 'ssl' and 'bullish' in m1_sig) or (sweep_side == 'bsl' and 'bearish' in m1_sig):
                # EXECUTION
                entry_price = m1[-1]['c']

                # Precision
                price_place = 2
                if self.simulator and symbol in self.simulator.contract_specs:
                    price_place = int(self.simulator.contract_specs[symbol].get('pricePlace', 2))
                tick_size = 1 / (10**price_place)

                # SL: 1 tick past FVG extreme
                fvg_data = detect_fvgs(m1, depth=self.params["fvg_depth"])
                if sweep_side == 'ssl':
                    fvg_extreme = fvg_data.get('nearest_fvg_bottom') or (entry_price * 0.995)
                    stop_price = fvg_extreme - tick_size
                else:
                    fvg_extreme = fvg_data.get('nearest_fvg_top') or (entry_price * 1.005)
                    stop_price = fvg_extreme + tick_size

                risk = abs(entry_price - stop_price)
                tp1 = entry_price + (risk * self.params["tp1_rrr"] if sweep_side == 'ssl' else -risk * self.params["tp1_rrr"])
                tp2 = entry_price + (risk * self.params["tp2_rrr"] if sweep_side == 'ssl' else -risk * self.params["tp2_rrr"])

                # Refine with Day Session Liquidity [CACHED]
                cache_key_liq_hub = f"{symbol}_liq_15m_{hub}"
                if self._cache.get(cache_key_liq_hub, {}).get('ts') == last_m15_ts:
                    liq_15m = self._cache[cache_key_liq_hub]['liq']
                else:
                    liq_15m = identify_liquidity(m15, lookback=self.params["m15_lookback"], swing_strength=self.params["m15_swing_strength"], hub_filter=hub)
                    self._cache[cache_key_liq_hub] = {'ts': last_m15_ts, 'liq': liq_15m}
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

                # Quantity & Rounding
                equity = market_data.get("equity") or (self.simulator.equity if self.simulator else config.INITIAL_EQUITY)
                qty = calculate_position_size(equity, config.RISK_PER_TRADE, entry_price, stop_price)

                qty_place = 3
                if self.simulator and symbol in self.simulator.contract_specs:
                    spec = self.simulator.contract_specs[symbol]
                    qty_place = int(spec.get('quantityPlace', 3))
                    qty = math.floor(qty * (10**qty_place)) / (10**qty_place)

                    min_qty = float(spec.get('minTradeUSDT', 5.0)) / entry_price
                    if qty < min_qty:
                        qty = math.ceil(min_qty * (10**qty_place)) / (10**qty_place)
                        if (qty * entry_price) / float(spec.get('maxLever', 20)) > equity * 0.95:
                            return None

                if self.record_milestone("Phase 7: 1m BOS2 (Entry Trigger)", m1[-1]['ts'], "1m"):
                    log.info(f"MUSTAFA_OV | {symbol} {sweep_side.upper()} Triggered! Target: Day Liquidity. Hub: {hub}")

                self.save_state(state_key, "COMPLETED", self.simulator)

                tp1_qty = round(qty * self.params["tp1_qty_ratio"], qty_place)
                return {
                    "side": "buy" if sweep_side == 'ssl' else "sell",
                    "entry_price": entry_price,
                    "stop_price": stop_price,
                    "exit_price": tp2,
                    "tp1_price": tp1,
                    "tp1_qty": tp1_qty,
                    "tp2_qty": qty - tp1_qty,
                    "qty": qty,
                    "bypass_global_filters": self.params["bypass_external_filters"] # [TECH-001] Pass toggle
                }

        return None

    def manage_position(self, position: Dict, market_data: Dict) -> Optional[Dict]:
        return None

    def _get_ohlcv(self, symbol: str, tf: str) -> List[dict]:
        if not self.simulator: return []
        return self.simulator.ohlcv.get(symbol, {}).get(tf, [])
