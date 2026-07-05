"""
# Range Sweep ATR Strategy v1.mustafa

## Overview
The Range Sweep ATR strategy uses volatility expansion to define trading ranges rather than
fixed time-based sessions. It identifies "Expansion Candles" on a higher timeframe (default 4H)
where the price range exceeds a significant multiplier of the preceding ATR (Average True Range).
The extremes of this expansion candle act as institutional liquidity anchors. The strategy
then waits for a sweep of these extremes on the 15m timeframe, confirmed by a precise 1m
reversal sequence.

## Goals & Rationale
- **Compounding Target**: Targets a net ROI of 2-5% per trade. Progressive capital growth
  is achieved by entering at the "inflection points" created by volatility extremes.
- **Frequency**: Low (1-5 setups per asset per month). This strategy is a "Sniper"
  module meant to run alongside higher-frequency session strategies to catch major
  market turns.
- **Selectivity**: Extremely high. By requiring a 5x ATR expansion, it filters out
  all "noise" and only activates when the market is in an overextended state.
- **Dynamic Anchoring**: Ranges are defined by the market's own volatility profile (ATR),
  making it adaptive. On ETH, a range might be $50, while on a lower-priced altcoin,
  it might be $0.05, but the *relative* expansion is the same.
- **Risk Management**: 0.5% risk-per-trade with fee-aware position sizing. Employs
  Aggressive Break-Even (moving SL to 50% profit point) upon TP1 to capitalize on the
  expected high-momentum reversal and remove risk from "blow-off" trades.

## Modules Used
- `ta/indicators/atr.py`: Detects expansion candles using the `is_expansion_candle`
  helper with a configurable multiplier (e.g., 5x ATR).
- `ta/patterns/structure.py`: Establishes 1H bias and 1m execution triggers (BOS).
- `ta/patterns/liquidity.py`: Identifies 15m targets formed after the expansion anchor.
- `ta/patterns/fvg.py`: Defines entry zones and SL levels on the 1m timeframe.
- `tools/trading_utils.py`: Fee-aware position sizing.

## The Intended Flow
1. **Expansion Detection (4H)**: Strategy monitors the 4H timeframe for a candle
   whose range (High-Low) is > 5x the preceding 14-period ATR.
2. **Anchor Range**: The High and Low of this expansion candle become the active "Range".
3. **Sequence Reset**: If a new 4H candle closes without being an expansion candle
   AND the sequence has not yet reached the "Sweep" phase (Phase 3), the range is discarded.
4. **Bias (1H)**: Establish trend bias from 1H market structure.
5. **Liquidity Sweep (15m)**: Wait for a wick sweep of the anchor range extreme
   opposite to the bias.
6. **Reversal Sequence (1m)**:
   - **BOS1**: Internal shift back toward bias.
   - **FVG**: Imbalance creation.
   - **Retest**: Validation of institutional interest.
   - **BOS2**: Final entry trigger.
7. **Execution**:
   - **SL**: 1 tick beyond the FVG extreme.
   - **TP1 (50%)**: 15m liquidity levels formed since the expansion (1:1.5+ RRR).
   - **TP2**: Next 15m level (1:2.5+ RRR).

## Limitations & Assumptions
- **Patience Requirement**: Expansion candles (5x ATR) are rare; the strategy
  may go days without a signal on a single asset.
- **Trend Exhaustion**: Assumes expansion candles at structural extremes represent
  exhaustion and liquidity raids rather than simple trend continuation.
"""

import logging
import math
from typing import Dict, Optional, Any, List
from strategies.base_strategy import JBaseStrategy
from tools.trading_utils import calculate_position_size
from ta.indicators.atr import is_expansion_candle
from ta.patterns.structure import identify_structure
from ta.patterns.liquidity import identify_liquidity
from ta.patterns.fvg import detect_fvgs
import config

log = logging.getLogger("strategies.mustafa_atr")

class RangeSweepATRStrategy(JBaseStrategy):
    def __init__(self, config_overrides: Optional[Dict] = None, simulator=None):
        super().__init__(
            name="range_sweep_ATR",
            version="1",
            author="mustafa",
            config_overrides=config_overrides
        )
        self.simulator = simulator
        self._cache = {} # [PERF-005] Cache for expensive calculations

        # [TECH-001] Explicit history requirements for authenticity
        # Values matched to technical module scan depths
        self.required_history = {"4H": 30, "1H": 120, "15m": 50, "1m": 100}

        # --- Strategy-Specific Parameters ---
        # [TECH-001] bypass_external_filters:
        # If True, the core Engine skips Layer 1 safety checks (Correlation, Cooldown, Regimes).
        # This strategy will still calculate its INTERNAL requirements (ATR Expansion, BOS)
        # regardless of this toggle, as they are mandatory for its logic.
        self.params = {
            "bypass_external_filters": True, # [TECH-001] Toggle for Layer 1 safety checks
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
            "tp1_qty_ratio": 0.5
        }

        if config_overrides:
            for k in self.params:
                if k in config_overrides:
                    self.params[k] = config_overrides[k]

    def get_entry_signal(self, market_data: Dict) -> Optional[Dict]:
        symbol = market_data["symbol"]

        range_tf = self.params["range_tf"]
        h4 = self._get_ohlcv(symbol, range_tf)
        h1 = self._get_ohlcv(symbol, "1H")
        m15 = self._get_ohlcv(symbol, "15m")
        m1 = self._get_ohlcv(symbol, "1m")

        if not h4 or not h1 or not m15 or not m1: return None

        # --- Phase 1: Expansion Detection [CACHED] ---
        state_key = f"{symbol}_atr_setup_state"
        state = self.get_state(state_key, self.simulator) or "IDLE"

        anchor_raw = self.get_state(f"{symbol}_atr_anchor", self.simulator) # {high, low, ts}
        anchor = None
        if anchor_raw and anchor_raw != "None":
            try:
                import ast
                if isinstance(anchor_raw, str):
                    anchor = ast.literal_eval(anchor_raw)
                else:
                    anchor = anchor_raw
            except:
                anchor = None

        # Check for NEW expansion candle
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

        # DEBUG
        # if len(h4) % 10 == 0:
        #    log.info(f"DEBUG | {symbol} {range_tf} len={len(h4)} exp={expansion.get('is_expansion')} ratio={expansion.get('ratio', 0):.2f}")

        if expansion['is_expansion']:
            cand = expansion['candle']
            new_anchor = {'high': cand['h'], 'low': cand['l'], 'ts': cand['ts']}

            # If sequence hasn't started (Phase 3), we always take the most recent expansion
            if state in ["IDLE", "WAITING_FOR_SWEEP"] or anchor is None:
                if anchor is None or cand['ts'] != anchor['ts']:
                    log.info(f"MUSTAFA_ATR | {symbol} Expansion Candle detected ({expansion['ratio']:.1f}x ATR)!")
                    self.save_state(f"{symbol}_atr_anchor", new_anchor, self.simulator)
                    self.save_state(state_key, "WAITING_FOR_SWEEP", self.simulator)
                    state = "WAITING_FOR_SWEEP"
                    anchor = new_anchor
                    self.record_milestone("Phase 1: ATR Expansion Anchor", cand['ts'], range_tf)

        # Check for range expiration
        # If a new 4H candle closes and we are still in WAITING_FOR_SWEEP,
        # and it's NOT the anchor candle, reset.
        if state == "WAITING_FOR_SWEEP" and anchor:
            if len(h4) < 2: return None
            last_closed_h4_ts = h4[-2]['ts']
            if last_closed_h4_ts > anchor['ts'] and not expansion['is_expansion']:
                # Sequence never started (no sweep), and a new normal candle appeared.
                self.save_state(state_key, "IDLE", self.simulator)
                self.save_state(f"{symbol}_atr_anchor", None, self.simulator)
                state = "IDLE"
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

            # Check last few 15m candles for a sweep of the anchor
            for c in m15[-8:]:
                if bias == 'bullish':
                    if c['l'] < anchor['low'] and c['c'] > anchor['low']:
                        sweep_detected = True; sweep_side = 'ssl'; break
                else: # bearish
                    if c['h'] > anchor['high'] and c['c'] < anchor['high']:
                        sweep_detected = True; sweep_side = 'bsl'; break

            if sweep_detected:
                self.record_milestone(f"Phase 2: 1H {bias.upper()} Bias", h1[-1]['ts'], "1H")
                self.record_milestone(f"Phase 3: 15m {sweep_side.upper()} Sweep", m15[-1]['ts'], "15m")
                log.info(f"MUSTAFA_ATR | {symbol} Sweep of ATR Anchor detected! Entering Execution.")
                self.save_state(state_key, "WAITING_FOR_BOS1", self.simulator)
                self.save_state(f"{symbol}_atr_sweep_side", sweep_side, self.simulator)
                state = "WAITING_FOR_BOS1"
            else:
                return None

        # --- Phase 4-7: Execution Sequence (1m) ---
        sweep_side = self.get_state(f"{symbol}_atr_sweep_side", self.simulator)
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
            if (sweep_side == 'ssl' and 'bullish' in m1_sig) or (sweep_side == 'bsl' and 'bearish' in m1_sig):
                # EXECUTION
                entry_price = m1[-1]['c']

                # Get asset precision
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

                # Position Sizing
                equity = market_data.get("equity") or (self.simulator.equity if self.simulator else config.INITIAL_EQUITY)
                qty = calculate_position_size(equity, config.RISK_PER_TRADE, entry_price, stop_price)

                # Hardening
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
                    log.info(f"MUSTAFA_ATR | {symbol} {sweep_side.upper()} Entry Triggered!")

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
        """
        Implements TP1 50% exit and Double-Down logic.
        """
        symbol = market_data["symbol"]
        m1 = self._get_ohlcv(symbol, "1m")
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
                log.info(f"MUSTAFA_ATR | DOUBLE DOWN for {symbol} {side}")
                self.save_state(f"{symbol}_atr_dd_count", dd_count + 1, self.simulator)
                return {"action": "double_size"}

        return None

    def _get_ohlcv(self, symbol: str, tf: str) -> List[dict]:
        if not self.simulator: return []
        return self.simulator.ohlcv.get(symbol, {}).get(tf, [])
