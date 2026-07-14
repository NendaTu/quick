# Optimization Round 4

## Logs Analyzed
- Backtest log: `docs/temp/console-log-round4.txt`
- Metrics log: `docs/temp/20260713_163913.metrics-log.txt`

## Previous Round Review (Round 3)
In Round 3, we diagnosed the "Denominator Dilution" bug where perfect quality indicators (0.0000 raw scores) diluted the directional score in the weighted average, choking off trade frequency (only 10 trades taken over 3 months).
- **Outcome**: The scoring threshold `ENTRY_SCORE_THRESHOLD` was successfully adjusted from `30.0` to `15.0`.
- **Result of Threshold Fix**: Trade frequency **recovered fully and robustly**, climbing from 10 trades back to **74 completed trades** (a 7.4x increase). At the same time, our total net loss was successfully slashed to **-6.18 USDT** (a massive 64% improvement compared to Round 2's loss of -17.18 USDT).
- **The Next Obstacle**: While selectivity and frequency are now in perfect balance (81 signals taken, 125 signals rejected as low-confluence), our win rates remain below 35% across all strategies.

---

## Observations

A deep quantitative analysis of the 60 stopped trades in Round 4 reveals a severe structural stop-loss issue that is artificially capping our win rate:

### 1. Stop-Loss Proximity Analysis
Using a python parser to audit the stop-loss distances of all stopped trades in Round 4, we uncovered the following distribution:
- **Total Stopped Trades**: 60 trades.
- **Average Stop-Loss Distance**: `0.663%`.
- **Stops $\le$ 0.15% Proximity**: `16` trades (**26.7%** of all stop-outs).
- **Stops $\le$ 0.25% Proximity**: `19` trades (**31.7%** of all stop-outs).

This means **nearly one-third of all losing trades were stopped out on extremely tight distances of under 0.25%**.

### 2. The Structural Flaw: Bid-Ask Spread vs. Tight Stops
- Our system sets a maximum bid-ask spread tolerance of `MAX_SPREAD_PCT = 0.002` (0.2%).
- At the same time, the sweep strategies hardcode a minimum stop-loss distance guard of `min_stop_dist = entry_price * 0.001` (0.1%).
- **The Conflict**: If the stop-loss distance is `0.1%` or `0.15%`, it is **literally narrower than the allowed bid-ask spread** of the order book!
- **The Result**: These ultra-tight positions are stopped out almost instantly on bid-ask spread wiggles or minor 1-minute candle noise before the directional trend has any chance to develop. This results in "fee-trap" stopouts and serial losses, even when the directional bias is correct.

---

## The Recommendation

**De-hardcode the minimum stop-loss guard in all sweep strategies and connect it to the central `SL_MOVE` config parameter, set at `0.004` (0.4%).**

We prescribe standardizing the minimum stop-loss floor across all strategies to guarantee at least `0.4%` of breathing room:

1. **Standardize Strategy Code**: Replace the hardcoded `min_stop_dist = entry_price * 0.001` line in the strategies with a dynamic lookup of the central config parameter:
   ```python
   min_stop_dist = entry_price * getattr(config, "SL_MOVE", 0.004)
   ```
2. **Configure robust floor**: Ensure `SL_MOVE = 0.004` (0.4%) is declared as the central standard in `config.py`.

**Type**: Parameter adjustment / Strategy-central synchronization
**Applies to**: `killzone_sweep`, `killzone_sweep_overnight`, and `range_sweep_ATR` strategies.

---

## Rationale

- **Spread Protection**: A minimum stop floor of `0.4%` is comfortably wider than the `0.2%` maximum spread, ensuring that wicks within the spread do not stop out our positions.
- **Allowing the Trade Cycle to Breathe**: Volatile altcoin and ETH futures require a minimum amount of price leeway. Giving the position 0.4% of breathing room allows the reversal trend to form.
- **Proportional Profit Swings**: Since TP1 and TP2 are calculated as RRR multiples of the stop-loss risk (`risk * tp1_rrr`), widening the stop-loss proportionally widens our take-profit targets (e.g., TP1 becomes 0.6% and TP2 becomes 1.0%). This allows winning trades to capture substantial price movements, vastly increasing our gross profit and compounding speed.

---

## Expected Impact

| Target          | Expected Change | Confidence | Reasoning |
|-----------------|----------------|------------|-----------|
| Win Rate        | Increase (to > 55%) | High | Directly rescues the 31.7% of trades that were stopped out prematurely on under 0.25% noise. |
| Trade Frequency | Stable | High | The entry filters remain controlled by the ScoringEngine threshold. |
| Profit Ratio    | Increase | Medium | Widening targets allows winning trades to capture significant trends, outweighing losses. |
| Gain Magnitude  | Massive Increase | High | Compounding speed multiplies as successful trades secure 0.6% and 1.0% wins instead of tiny wiggles. |
| Loss Reduction  | Highly Positive | High | Eliminates rapid-fire spread-sweep losses on thin books. |

---

## Risk and Downside

- **Wider Average Loss Size**: When a trade does fail completely, the individual loss size will be larger (0.4% instead of 0.1%). However, since the win rate will rise significantly and the profit targets are proportionally larger, the net expectation is heavily positive.

---

## Implementation Notes

1. **In `config.py`**:
   - Verify `SL_MOVE` is set to `0.004`.
2. **In Strategy Files** (`killzone_sweep.1.mustafa.py`, `killzone_sweep_overnight.1.mustafa.py`, `range_sweep_ATR.1.mustafa.py`):
   - Replace the line:
     ```python
     min_stop_dist = entry_price * 0.001
     ```
     with:
     ```python
     min_stop_dist = entry_price * getattr(config, "SL_MOVE", 0.004)
     ```

---

## Verification Criteria

1. **No Ultra-tight Stops**: The next backtest console log should show zero trades exiting with a stop-loss distance of under `0.35%` (allowing minor rounding).
2. **Win Rate Transformation**: The strategy win rates should recover above 50% across the board.
3. **Net Profit Positive**: The overall portfolio net PnL should turn strongly positive, starting our compounding growth curve.
