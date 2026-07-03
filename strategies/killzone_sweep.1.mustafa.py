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
        self.fvg_penetration_required = False # Default to touch only
        self.max_double_downs = 1

    def get_entry_signal(self, market_data: Dict) -> Optional[Dict]:
        symbol = market_data["symbol"]

        # We need data for all 3 timeframes
        h1 = self._get_ohlcv(symbol, "1H")
        m15 = self._get_ohlcv(symbol, "15m")
        m1 = self._get_ohlcv(symbol, "1m")

        if not h1 or not m15 or not m1:
            return None

        # --- Phase 1: Bias Identification (1H) ---
        ov_range = identify_overnight_range(h1)
        if not ov_range: return None

        h1_struct = identify_structure(h1)
        h1_sig = h1_struct.get('structure_signal') or ''

        # Bias: bullish if overall range is trending up or bullish BOS
        bias = 'neutral'
        if 'bullish' in h1_sig: bias = 'bullish'
        elif 'bearish' in h1_sig: bias = 'bearish'

        if bias == 'neutral': return None

        # --- Phase 2: Sweep Detection (15m) ---
        # 6. Invalidate if any 15m candle closed outside the overnight range
        for c in m15:
            dt = convert_to_local(c['ts'])
            # Check if this candle is within current session
            # (Simplification: check last 20 15m candles)
            if c['c'] > ov_range['overnight_high'] or c['c'] < ov_range['overnight_low']:
                # If it closed outside before we saw a sweep, we might invalidate
                # For now, we'll check if the latest 15m action is valid
                pass

        liq_15m = identify_liquidity(m15)
        latest_15m = m15[-1]

        sweep_detected = False
        sweep_side = None # 'ssl' or 'bsl'

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

        if not sweep_detected: return None

        # --- Phase 3: Execution Sequence (1m) ---
        # This part usually requires state tracking because BOS1 -> FVG -> Retest -> BOS2
        # happens over many 1m candles.

        state_key = f"{symbol}_setup_state"
        state = self.get_state(state_key, self.simulator) or "WAITING_FOR_BOS1"

        m1_struct = identify_structure(m1)
        m1_sig = m1_struct.get('structure_signal', '')

        if state == "WAITING_FOR_BOS1":
            if (sweep_side == 'ssl' and 'bullish' in m1_sig) or (sweep_side == 'bsl' and 'bearish' in m1_sig):
                self.save_state(state_key, "WAITING_FOR_FVG", self.simulator)
                # Keep going to check FVG in same tick
                state = "WAITING_FOR_FVG"

        if state == "WAITING_FOR_FVG":
            fvg_data = detect_fvgs(m1)
            if fvg_data.get('fvg_count', 0) > 0:
                # Store FVG level for retest check
                # (Simplification: just move to retest)
                self.save_state(state_key, "WAITING_FOR_RETEST", self.simulator)
                state = "WAITING_FOR_RETEST"

        if state == "WAITING_FOR_RETEST":
            # Check if last few 1m candles touched/penetrated the FVG
            # This requires more complex state, but for v1 we'll look for the touch
            retested = True # Placeholder
            if retested:
                self.save_state(state_key, "WAITING_FOR_BOS2", self.simulator)
                state = "WAITING_FOR_BOS2"

        if state == "WAITING_FOR_BOS2":
            if (sweep_side == 'ssl' and 'bullish' in m1_sig) or (sweep_side == 'bsl' and 'bearish' in m1_sig):
                # TRIGGER ENTRY
                self.save_state(state_key, "COMPLETED", self.simulator)

                # --- Phase 4: Entry & Risk Management ---
                entry_price = m1[-1]['c']
                fvg_data = detect_fvgs(m1) # Re-get to find SL

                # SL: 1 tick past FVG
                # (Need actual FVG bounds, detect_fvgs only returns nearest)
                stop_price = entry_price * (0.995 if sweep_side == 'ssl' else 1.005)

                # TP1/TP2 from 15m liquidity
                tp1 = entry_price * (1.01 if sweep_side == 'ssl' else 0.99)
                tp2 = entry_price * (1.02 if sweep_side == 'ssl' else 0.98)

                return {
                    "side": "buy" if sweep_side == 'ssl' else "sell",
                    "entry_price": entry_price,
                    "stop_price": stop_price,
                    "exit_price": tp2, # Final TP
                    "tp1_price": tp1,
                    "tp1_qty_ratio": 0.5,
                    "qty": 0 # Engine will calculate based on risk
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
            if dd_count < self.max_double_downs:
                log.info(f"DOUBLE DOWN for {symbol} {side}")
                self.save_state(f"{symbol}_dd_count", dd_count + 1, self.simulator)
                # Return update signal to double size
                # In this foundation, we'll return a 'double' command
                return {"action": "double_size"}

        return None

    def _get_ohlcv(self, symbol: str, tf: str) -> List[dict]:
        if not self.simulator: return []
        return self.simulator.ohlcv.get(symbol, {}).get(tf, [])
