"""
# Killzone Sweep Strategy v1.mustafa

## Overview
This strategy implements a sophisticated multi-timeframe (MTF) sequence focused on
institutional liquidity sweeps during session killzones. It identifies bias on 1H,
monitors for liquidity raids on 15m, and executes via a two-stage Break of Structure (BOS)
and Fair Value Gap (FVG) sequence on the 1m timeframe.

## Goals
- Target high-probability reversals after retail liquidity is swept.
- ROI: Dynamic based on 15m liquidity levels, minimum 1:1.5 RRR for TP1 and 1:2.5 for TP2.
- Frequency: Selective, targeting 1-3 high-quality setups per session per asset.

## Modules Used
- `ta/patterns/sessions.py`: For current session and overnight range identification.
- `ta/patterns/structure.py`: For BOS/MSS detection (1H and 1m).
- `ta/patterns/liquidity.py`: For BSL/SSL and internal liquidity targets (15m).
- `ta/patterns/fvg.py`: For execution-level gap identification (1m).
- `ta/patterns/swings.py`: For swing point identification.

## The Intended Flow
1. **Bias (1H)**: Determine session bias based on the preceding overnight range (Prior Close to Session Open).
   Confirm bias with 1H BOS.
2. **Setup (15m)**: Monitor for a liquidity sweep (wick) of the overnight range extreme *opposite* to bias.
   Invalidate if any 15m candle closes outside the range before the sweep.
3. **Execution (1m)**:
   - Identify BOS1 on the return from the sweep.
   - Identify an FVG formed during or around BOS1.
   - Wait for an FVG retest (touch/penetration).
   - Identify BOS2 following the retest.
   - Entry on BOS2 close.
4. **Risk Management**:
   - SL: 1 tick past the execution FVG.
   - TP1 (50%): First 15m liquidity level at/beyond 1.5 RRR. Move SL to BE.
   - TP2: Next 15m liquidity level at/beyond 2.5 RRR.
   - Scaling: Double position on engulfing/consecutive retracements that close short of entry.

## Limitations
- Requires significant history for 1H/15m analysis.
- Highly dependent on precise execution timing on the 1m timeframe.
"""

import logging
from typing import Dict, Optional, Any, List
from strategies.base_strategy import JBaseStrategy
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

        # --- Strategy-Specific Parameters (with overrides) ---
        self.params = {
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

        # --- Phase 1: Bias Identification (1H) ---
        ov_range = identify_overnight_range(h1, prior_close_hour=self.params["prior_close_hour"])
        if not ov_range:
            return None

        self.record_milestone("Phase 1: 1H Overnight Range", h1[-1]['ts'], "1H")

        h1_struct = identify_structure(h1, strength=self.params["h1_strength"])
        h1_sig = h1_struct.get('structure_signal') or ''

        # Bias: bullish if overall range is trending up or bullish BOS
        bias = 'neutral'
        if 'bullish' in h1_sig: bias = 'bullish'
        elif 'bearish' in h1_sig: bias = 'bearish'

        if bias == 'neutral':
            return None

        self.record_milestone(f"Phase 2: 1H {bias.upper()} Bias", h1[-1]['ts'], "1H")

        # --- State Management ---
        state_key = f"{symbol}_setup_state"
        state = self.get_state(state_key, self.simulator) or "IDLE"

        # Session Tracking for Reset
        curr_session = ov_range.get('session')
        last_session = self.get_state(f"{symbol}_last_session", self.simulator)

        if curr_session != last_session:
            self.record_milestone(f"Phase 0: {curr_session.upper()} Session Start", h1[-1]['ts'], "1H")
            self.save_state(f"{symbol}_last_session", curr_session, self.simulator)
            self.save_state(state_key, "IDLE", self.simulator)
            state = "IDLE"

        # --- Phase 2: Sweep Detection (15m) ---
        liq_15m = identify_liquidity(m15, lookback=self.params["m15_lookback"], swing_strength=self.params["m15_swing_strength"])

        if state == "IDLE":
            latest_15m = m15[-1]
            sweep_detected = False
            sweep_side = None

            if bias == 'bullish':
                # Look for SSL sweep (sweep of overnight low)
                if latest_15m['l'] < ov_range['overnight_low'] and latest_15m['c'] > ov_range['overnight_low']:
                    sweep_detected = True
                    sweep_side = 'ssl'
            else: # bearish
                # Look for BSL sweep (sweep of overnight high)
                if latest_15m['h'] > ov_range['overnight_high'] and latest_15m['c'] < ov_range['overnight_high']:
                    sweep_detected = True
                    sweep_side = 'bsl'

            if sweep_detected:
                if self.record_milestone(f"Phase 3: 15m {sweep_side.upper()} Sweep", latest_15m['ts'], "15m"):
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

            if fvg_data.get('nearest_fvg_type') == target_fvg and fvg_data.get('nearest_fvg_state') in ['engaged', 'mitigated']:
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
                # TRIGGER ENTRY
                self.record_milestone("Phase 7: 1m BOS2 (Entry Trigger)", m1[-1]['ts'], "1m")
                self.save_state(state_key, "COMPLETED", self.simulator)

                # --- Phase 4: Entry & Risk Management ---
                entry_price = m1[-1]['c']

                # SL: 1 tick past FVG (opposite side)
                # Bullish: 1 tick below FVG bottom. Bearish: 1 tick above FVG top.
                fvg_data = detect_fvgs(m1, depth=self.params["fvg_depth"])
                # Approximation using nearest fvg dist
                fvg_mid = entry_price / (1 + fvg_data.get('nearest_fvg_dist', 0))
                stop_price = fvg_mid * (0.998 if sweep_side == 'ssl' else 1.002)

                # TP1/TP2 from 15m liquidity
                # 14. TP1 (50%) at first upcoming 15m liquidity at/beyond 1:1.5 RRR
                risk = abs(entry_price - stop_price)
                min_tp1_dist = risk * self.params["tp1_rrr"]
                min_tp2_dist = risk * self.params["tp2_rrr"]

                tp1 = entry_price + (min_tp1_dist if sweep_side == 'ssl' else -min_tp1_dist)
                tp2 = entry_price + (min_tp2_dist if sweep_side == 'ssl' else -min_tp2_dist)

                # Refine with actual liquidity levels
                if sweep_side == 'ssl':
                    # Bullish: look for BSL targets above min_tp
                    for level in liq_15m.get('all_bsl', []):
                        if level >= tp1:
                            tp1 = level
                            break
                    for level in liq_15m.get('all_bsl', []):
                        if level >= tp2:
                            tp2 = level
                            break
                else:
                    # Bearish: look for SSL targets below min_tp
                    for level in liq_15m.get('all_ssl', []):
                        if level <= tp1:
                            tp1 = level
                            break
                    for level in liq_15m.get('all_ssl', []):
                        if level <= tp2:
                            tp2 = level
                            break

                return {
                    "side": "buy" if sweep_side == 'ssl' else "sell",
                    "entry_price": entry_price,
                    "stop_price": stop_price,
                    "exit_price": tp2,
                    "tp1_price": tp1,
                    "tp1_qty_ratio": self.params["tp1_qty_ratio"],
                    "qty": 0
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
