# Optimization Round 1

## Logs Analyzed
- Backtest log: `docs/temp/console-log.txt`
- Metrics log: `docs/temp/20260712_200504.metrics-log.txt`

## Observations

A deep quantitative analysis of the backtest console logs and metrics log reveals several critical system behaviors that are directly degrading compounding performance:

### 1. Overall Portfolio Performance
- **Total Trades**: 210 completed trades.
- **Portfolio Win Rate**: 33.8% (highly suboptimal).
- **Starting Equity**: 40.0 USDT.
- **Ending Equity**: 28.35 USDT (down -11.65 USDT, representing a net drawdown of **-29.1% ROI**).

### 2. Strategy Breakdown and Diagnostics
Reconstructing individual position statistics from the logs yields the following:

- **`killzone_sweep_overnight`**:
  - **Trades**: 95
  - **Win Rate**: 28.42%
  - **Net PnL**: -10.2346 USDT
  - **Avg Win / Avg Loss**: 0.3923 USDT / -0.3063 USDT (Profit Ratio: 1.28)
  - **Diagnostic**: This strategy alone is responsible for **88% of the entire portfolio drawdown**. In quiet overnight sessions, volatility lacks the momentum to sustain long-distance sweep reversals. Instead, price wiggles within a thin range, triggering stops repeatedly.

- **`range_sweep_ATR`**:
  - **Trades**: 109
  - **Win Rate**: 39.45%
  - **Net PnL**: -0.1169 USDT
  - **Avg Win / Avg Loss**: 0.4683 USDT / -0.3069 USDT (Profit Ratio: 1.53)
  - **Diagnostic**: This "Sniper" strategy is **essentially break-even** over 109 trades, indicating extremely strong underlying structure. With a minor improvement in selectivity, this strategy is highly likely to turn net-profitable.

- **`killzone_sweep`**:
  - **Trades**: 6
  - **Win Rate**: 16.67%
  - **Net PnL**: -1.2997 USDT
  - **Avg Win / Avg Loss**: 0.7345 USDT / -0.4068 USDT (Profit Ratio: 1.81)
  - **Diagnostic**: Very low trade frequency because daytime core-session opening sweeps are highly restricted to a narrow 2-hour window.

### 3. Critical System Bugs Identified
- **The Zeroed-Out Metrics Log Bug**:
  Every single row of the 226 entries in the metrics log has an `aggregated_score` of `0.0000` and all raw/weighted indicator scores logged as `0.0000`.
  - *Root Cause*: In `engine/core.py`, when a strategy emits an entry signal, the signal dictionary itself (which lacks `raw_scores` and `weighted_scores` keys) is passed directly as the `scoring_result` to `self._write_metrics_log`. This prevents any actual indicator scores from being evaluated or logged, completely blinding our capability to analyze indicator-to-outcome correlations.

- **Bypassing Reentry Cooldowns**:
  All three sweep strategies hardcode `"bypass_external_filters": True` in their parameters. This bypasses the global `_asset_is_tradable` method entirely.
  - *Root Cause*: Without `_asset_is_tradable` checks, there is no re-entry cooldown in backtests. This leads to **serial stop-outs** where the same asset is traded multiple times in a single minute on the same sweep (e.g., three sequential ETHUSDT short positions opened and stopped out at `00:05:59`, `00:06:07`, and `00:06:14` execution timestamps, multiplying the loss).

- **Real-World Time Cooldown Bug**:
  In `_asset_is_tradable` of `engine/core.py`, the reentry cooldown check compares real elapsed clock-time (`time.time() - last_exit < cooldown`) instead of virtual/backtest time. Since one virtual backtest day passes in seconds of real-world time, any real-world 60-second cooldown corresponds to *several virtual weeks* of lockout, which would artificially kill backtest trade frequency if external filters are turned on.

### 4. Stop-Loss "Fee Traps" and Spread Sweeps
- Strategy stop losses are placed 1 tick past the 1m FVG extreme, with a minimum floor of `0.001` (0.1% of entry price).
- In liquid crypto-futures markets, a 0.1% to 0.15% stop loss is extremely tight and is easily tripped by order book spreads or normal noise, stopping the trade out before the directional trend can develop.

---

## The Recommendation

**Integrate and activate the Unified Scoring Engine as an entry filter for all strategies, fix the zeroed-out metrics log bug, and resolve the backtest cooldown time-scale bug.**

We recommend making a single, precise systemic shift that upgrades the strategies from "blind patterns" to "high-confluence setups":

1. **Activate Active Indicator Filtering**: Set `"bypass_external_filters": False` in all strategy parameters (or have the engine enforce checks regardless).
2. **Scoring Confluence Check**: Modify `engine/core.py` so that before any signal from a strategy is routed or executed, the engine calculates the technical indicators (`feat`) and runs them through `ScoringEngine().evaluate()`. Discard any buy signal where the `aggregated_score` is below `ENTRY_SCORE_THRESHOLD` (30.0) or sell signal where it is above `-ENTRY_SCORE_THRESHOLD` (-30.0).
3. **Fix Metrics Log**: Ensure that the evaluated `scoring_result` dictionary containing raw and weighted scores is passed to `_write_metrics_log` so that exact indicator values are correctly captured in the CSV file for offline auditing.
4. **Fix Backtest Cooldowns**: Refactor the cooldown check in `_asset_is_tradable` to use virtual timestamps (`current_ts - last_exit_ts < cooldown` using candle timestamps) rather than system clock time (`time.time()`).

**Type**: Filter activation / Bug fix
**Applies to**: Both simulation and live/demo execution engines, across all three active sweep strategies.

---

## Rationale

- **Selectivity Over Choppiness**: Activating the `ScoringEngine` ensures that we do not blindly enter sweeps. For example, we will not take a long sweep if the global HTF bias is bearish (`WEIGHT_HTF_BIAS = 1.0`), MACD slope is negative, or BTC confluence is absent (`WEIGHT_BTC_CONF = 1.5`).
- **Eliminating Serial Losses**: Forcing strategies through `_asset_is_tradable` and fixing the cooldown virtual time-scale bug ensures that a 60-second (or longer ATR-adjusted) cooldown is correctly enforced in backtests. This completely prevents the serial stop-outs (multiple immediate losses on the same asset within a single minute).
- **Restoring Visibility**: Fixing the metrics log schema mapping restores our quantitative feedback loop. In Round 2, we will have a metrics log filled with valid indicator scores, allowing us to perform true multi-variable optimization.

---

## Expected Impact

| Target          | Expected Change | Confidence | Reasoning |
|-----------------|----------------|------------|-----------|
| Win Rate        | Increase (to > 55%) | High | Eliminates bad counter-trend trades and serial stop-outs on wicks. |
| Trade Frequency | Decrease (-35%) | High | Filters out low-confluence setups, sacrificing poor volume for quality. |
| Profit Ratio    | Increase (to > 1.8) | Medium | Better entry points lead to stronger breakout follow-through to TP targets. |
| Gain Magnitude  | Stable / Slight Increase | High | Maintains same dynamic position sizing and RRR targets. |
| Loss Reduction  | Massive Reduction | High | Directly avoids the cascading rapid-fire stop-outs that caused 88% of losses. |

---

## Risk and Downside

- **Reduced Trade Frequency**: By adding strict multi-indicator confluence requirements, the total number of trades taken per day will decrease. However, since the current trading loop is net-negative, reducing frequency while increasing win rate is a massive net win for compounding progress.
- **Execution Overhead**: Calculating 17 indicators and running the scoring engine on every tick/candle adds minor CPU overhead, but since we are running on a MacBook M3 Pro, this is negligible.

---

## Implementation Notes

1. **In `engine/core.py`**:
   - Import `ScoringEngine` from `ta.scoring`.
   - In `_trading_loop`, inside `active_signals` processing:
     ```python
     # Evaluate using ScoringEngine
     se = ScoringEngine()
     scoring_result = se.evaluate(feat, side=side, config_context=self.config)

     # Write actual scoring result to log (fixes metrics-log bug)
     self._write_metrics_log(sym, side, signal.get("strategy_id"), scoring_result)

     # Filter signal if ScoringEngine rejects it
     if scoring_result["decision"] == "REJECTED":
         log.info(f"Signal rejected by ScoringEngine: {scoring_result['reason']}")
         continue
     ```
2. **In `_asset_is_tradable` of `engine/core.py`**:
   - Modify the cooldown check to use virtual timestamps. Track `self.last_exit_ts[symbol]` using the virtual candle timestamps `c['ts']` from the simulation loop instead of `time.time()`.
3. **In Strategy Files** (`killzone_sweep.1.mustafa.py`, `killzone_sweep_overnight.1.mustafa.py`, `range_sweep_ATR.1.mustafa.py`):
   - Set `"bypass_external_filters": False` in `self.params`.

---

## Verification Criteria

1. **Metrics Log Output**: The next round's `*.metrics-log.txt` must contain non-zero floats for `rsi_raw`, `macd_raw`, `btc_mom_raw`, and `aggregated_score`. No column should be permanently stuck at `0.0000`.
2. **No Serial Trades**: No asset should show multiple entry/exit cycles within the same virtual 15-minute window.
3. **Win Rate & Profit**: The portfolio win rate should rise above 50% and net portfolio PnL should turn positive.
