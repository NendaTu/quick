# Optimization Round 2

## Logs Analyzed
- Backtest log: `docs/temp/console-log-round2.txt`
- Metrics log: Not provided for this round (analyzed via Console Log entries and strategy state tracing)

## Previous Round Review (Round 1)
In Round 1, we recommended integrating the ScoringEngine, fixing the metrics log schema formatting, and resolving the backtest real-world vs. virtual cooldown bug.
- **Outcome**: The implementing agent successfully integrated the `ScoringEngine` filter, mapped correct non-zero metrics to the CSV file, restored reentry cooldowns, and resolved the real-world vs. virtual time-scale cooldown bug.
- **Result of Cooldown Fix**: Enforcing virtual cooldowns successfully allowed strategies like `killzone_sweep` to increase trade frequency from 6 to 24 trades, and allowed all strategies to run fully and cleanly in backtests without being locked out.
- **The Next Obstacle**: However, fixing the cooldown bug exposed a deeper, cascading logical flaw in the state-machines of our sweep strategies: the **"Zombie Sweep" Bug**.

---

## Observations

A deep analysis of the Round 2 backtest console log reveals a critical logical loop that is severely dragging down performance across all strategies:

### 1. Performance Overview
- **Total Trades**: 256 trades (increased from 210 in Round 1).
- **Ending Equity**: 22.82 USDT (loss of -17.18 USDT, or **-42.95% ROI** on 40.0 USDT starting capital).
- **Strategy Performance**:
  - `killzone_sweep_overnight`: 107 trades, 28.0% Win%, -8.73 USDT PnL.
  - `range_sweep_ATR`: 125 trades, 36.0% Win%, -2.85 USDT PnL.
  - `killzone_sweep`: 24 trades, 16.7% Win%, -5.61 USDT PnL.

### 2. Diagnosis: The "Zombie Sweep" Bug
An audit of the entry logs reveals that assets are frequently entered multiple times on the exact same sweep and session range. For example, look at `ETHUSDT` under `killzone_sweep_overnight`:
- **03:05:29**: FILLED ENTRY ETHUSDT BUY @ 1965.51
- **03:05:38**: FILLED ENTRY ETHUSDT BUY @ 1957.77 (9 execution seconds later)
- **03:05:41**: FILLED ENTRY ETHUSDT SELL @ 1931.33 (3 execution seconds later)
- **03:05:41**: FILLED ENTRY ETHUSDT SELL @ 1932.83 (0 execution seconds later)
- **03:05:43**: FILLED ENTRY ETHUSDT BUY @ 1971.24 (2 execution seconds later)
- **03:05:47**: FILLED ENTRY ETHUSDT BUY @ 1985.39 (4 execution seconds later)
- **03:05:48**: FILLED ENTRY ETHUSDT BUY @ 2053.08 (1 execution second later)

This represents **7 trades on a single asset within 20 execution seconds**! A similar pattern occurred on `XPTUSDT` with 10 rapid-fire entries.

#### Why is this happening?
1. **Cooldown Expiration in Virtual Time**: 10 real-world execution seconds in a fast backtest corresponds to ~2.4 virtual hours. This means our 1-hour virtual cooldown is fully expired, and the strategy state machine resets from `COMPLETED` back to `IDLE` correctly.
2. **Session Persistence**: The "Overnight Session" lasts 17.5 virtual hours. When the strategy resets to `IDLE` at virtual hour 18:15, it scans `m15[-32:]` (the last 8 virtual hours) for a sweep.
3. **The Logical Flaw**: The sweep that occurred at virtual hour 17:00 is **still inside the 8-hour scan window**!
4. **The Zombie Loop**: The strategy detects the same sweep *again*, runs the catch-up sequence *again*, and triggers another entry *again*. This repeat-loop continues hour after hour for the entire session, generating up to 10 duplicate losing trades on the **exact same sweep**.

---

## The Recommendation

**Implement "Zombie Sweep" Prevention by tracking and blocking duplicate trades on previously traded sweeps.**

We prescribe a precise logical gate inside all three sweep strategies to ensure that once a sweep is traded, it can never be traded again:

1. **Track the Traded Sweep**: When an entry is triggered (Phase 7), save the active sweep's timestamp:
   - For `killzone_sweep`: `self.save_state(f"{symbol}_last_traded_sweep_ts", sweep_ts, self.simulator)`
   - For `killzone_sweep_overnight`: `self.save_state(f"{symbol}_ov_last_traded_sweep_ts", sweep_ts, self.simulator)`
   - For `range_sweep_ATR`: `self.save_state(f"{symbol}_atr_last_traded_sweep_ts", sweep_ts, self.simulator)`
2. **Filter Incoming Sweeps**: In Phase 3 (Sweep Detection), after a sweep is detected at `sweep_ts`, load the corresponding `last_traded_sweep_ts`. If `sweep_ts <= float(last_traded_sweep_ts)`, **strictly reject and skip the sweep**.

**Type**: Parameter adjustment / Logic enhancement
**Applies to**: `killzone_sweep`, `killzone_sweep_overnight`, and `range_sweep_ATR` strategies.

---

## Rationale

- **High-Fidelity Selectivity**: This change completely eliminates duplicate "echo" entries on the same price wiggles. By taking only the first primary breakout and blocking the rest, we protect our margin and drastically reduce drawdowns.
- **Accurate Compounding**: Instead of losing 7-10 times on a single false breakout or bad range, we suffer at most a single stop-loss. This preserves capital and allows positive-compounding trades to grow.
- **Saves Capital on Choppy/Overnight Markets**: Overnight ranges are notoriously quiet, making them highly susceptible to multiple narrow fake-outs. Restricting the bot to one trade per sweep is mathematically the single most effective shield.

---

## Expected Impact

| Target          | Expected Change | Confidence | Reasoning |
|-----------------|----------------|------------|-----------|
| Win Rate        | Increase (to > 50%) | High | Eliminates hundreds of duplicate, low-probability stopped-out trades. |
| Trade Frequency | Decrease (-50%) | High | Drops from 256 trades to ~100 high-quality unique setups. |
| Profit Ratio    | Increase | Medium | Avoiding multi-losses on a single sweep boosts the win-to-loss ratio. |
| Gain Magnitude  | Stable | High | Individual TP and reinvestment calculations remain unaffected. |
| Loss Reduction  | Massive Reduction | High | Directly saves us from the 7x and 10x cascading stop-outs seen on ETH and XPT. |

---

## Risk and Downside

- **Reduced Trade Frequency**: The raw trade count will drop by about half because we are eliminating duplicates. However, this is precisely what is needed to stop the equity bleed and make compounding possible.
- **Missed Re-entries on True Reversals**: If a sweep occurs, a trade is taken and stopped, and then a *new* sweep of the same level occurs later, it would be blocked if the timestamp is identical. However, in practice, a new sweep would have a later timestamp (`sweep_ts > last_traded_sweep_ts`) and would still be permitted.

---

## Implementation Notes

1. **In `killzone_sweep_overnight.1.mustafa.py`**:
   - In Phase 3 (Sweep Detection), load `last_traded_sweep = self.get_state(f"{symbol}_ov_last_traded_sweep_ts", self.simulator)`.
   - If `last_traded_sweep` is not None and `sweep_ts <= float(last_traded_sweep)`: skip setting state to `WAITING_FOR_BOS1` and return `None`.
   - In Phase 7 (Entry Trigger), save the active sweep's timestamp:
     ```python
     self.save_state(f"{symbol}_ov_last_traded_sweep_ts", sweep_ts, self.simulator)
     ```
2. **Apply Identical Logic to**:
   - `killzone_sweep.1.mustafa.py` (using key `f"{symbol}_last_traded_sweep_ts"` and `sweep_ts`).
   - `range_sweep_ATR.1.mustafa.py` (using key `f"{symbol}_atr_last_traded_sweep_ts"` and `sweep_ts`).

---

## Verification Criteria

1. **No Duplicate Trades**: The console log should never show multiple filled entries on the same asset and strategy within the same overnight or daytime session unless they are on distinct, sequentially later wicks.
2. **Significant Drawdown Reduction**: Portfolio PnL should show a dramatic turn toward profitability with a major reduction in net losing trades.
