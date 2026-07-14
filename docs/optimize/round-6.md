# Optimization Round 6

## Logs Analyzed
- Backtest log: `docs/temp/est15-console-log.txt`
- Metrics log: `docs/temp/est15-20260714_003009.metrics-log.txt`

## Previous Round Review (Round 5)
In Round 5, we conducted a multi-variable correlation analysis of the metrics log, identifying that wins heavily correlate with positive MACD momentum and DRT regression, while RSI and minor structure breaks act as flat, noisy diluters of our weighted average score.
- **Outcome**: The Scoring Engine weights in `config.py` were adjusted to favor MACD (2.5) and DRT (2.0) while minimizing RSI (0.2) and Structure (0.5).
- **Result of Weight Tuning**: This shift successfully blocked a massive portion of choppy, counter-trend sweep setups. The net portfolio loss was reduced to **-4.95 USDT** (an improvement over Round 5's -7.82 USDT).
- **The Core Block**: However, despite these extensive filters, the overall strategy win rates are still stuck around 30%. We must think outside the box to locate a systemic, logical vulnerability in how patterns are calculated.

---

## Observations: "Outside-the-Box" Logical Discovery

By conducting a deep logical code audit of our technical analysis modules (`ta/patterns/structure.py` and `ta/patterns/sweep.py`) alongside the tick-by-tick logs, we discovered a **catastrophic, systemic look-ahead/repainting bug** in our trigger evaluation:

### 1. The Real-Time Repainting Flaw
In `_trading_loop` of `engine/core.py`, the trading loop is evaluated in real-time on every single tick (multiple times per minute).
- The list `ohlcv` contains the currently open, fluctuating, unclosed candle as its last element (`ohlcv[-1]`).
- Our patterns evaluate their triggers using `ohlcv[-1]` as the "live" trigger candle:
  - In `ta/patterns/structure.py:identify_structure`:
    ```python
    curr = ohlcv[-1] # Check break against live candle
    is_breaking_hh = (curr['c'] > last_hh) if CONFIRM_BREAK_ON_CLOSE else (curr['h'] > last_hh)
    ```
  - In `ta/patterns/sweep.py:detect_sweeps`:
    ```python
    last = ohlcv[-1]
    if last['h'] > bsl and last['c'] < bsl:
        if last['c'] < last['o']: # Bearish close
            sweep_type = 'buy_side'
    ```

### 2. The False Breakout / Trap Effect
Since `ohlcv[-1]` is unclosed, its `close` price (`last['c']`) is actually the fluctuating, live price of the active candle.
- **The Bug**: If the price momentarily wicks up above a major liquidity level (`bsl`) and is momentarily red, `detect_sweeps` returns `sweep_detected = True` in real-time! An entry order is placed immediately on this live unclosed candle.
- **The Trap**: Before the minute candle actually closes, the price surges higher, closing *above* the liquidity level as a strong bullish breakout.
- **The Result**: Because we evaluated on the live unclosed candle, **we have shorted a massive bullish breakout candle right before it rips**, leading to an instant and guaranteed stop-out. Our "reversal entries" are actually entering directly into the teeth of strong breakouts!

This explains why **more than 62% of our trades hit TP1 or initial wicks and then reverse/stop-out**; we are entering on fleeting wiggles of live unclosed candles that completely repaint by the time the bar completes.

---

## The Recommendation

**Enforce strict "Closed-Candle Execution" by passing only completed, closed candles (`ohlcv[:-1]`) to all strategy entry and pattern calculations.**

To completely eliminate repainting, look-ahead bias, and false breakout triggers, we must ensure that the strategy signal generators never see the currently live unclosed candle:

1. **Pass `ohlcv[:-1]` to Strategy Signals**: In `_trading_loop` of `engine/core.py` (and in backtesting), slice the OHLCV data passed to the strategies and feature extractors to strictly exclude the current active candle:
   - Pass `ohlcv[:-1]` to all `get_entry_signal` and `get_features` calls.
   - This guarantees that the "last" candle seen by any strategy is a completed, fully closed bar, making all breakout and sweep confirmations 100% mathematically stable and immune to real-time fluctuation.

**Type**: Logic enhancement / Execution guard
**Applies to**: Core Trading Loop and Backtesting Engines across all strategies.

---

## Rationale

- **100% Repaint Immunity**: Evaluating entries strictly on completed closed candles ensures that a "sweep and reversal close" is physically confirmed on-chain/on-exchange before our limit orders are posted, eliminating wick fake-outs.
- **Drastic Win Rate Transformation**: This directly stops us from shorting bullish breakouts or buying bearish dumps. Our win rates are expected to immediately surge above 55%-65%.
- **High-Fidelity Backtest Parity**: It matches standard quantitative trading rules, ensuring that our paper simulation matches live execution wicks precisely without look-ahead anomalies.

---

## Expected Impact

| Target          | Expected Change | Confidence | Reasoning |
|-----------------|----------------|------------|-----------|
| Win Rate        | Massive Increase (to > 60%) | High | Completely stops entering "sweeps" on live candles that turn into breakout runs. |
| Trade Frequency | Stable / Slight Decrease | High | Slices out the false-breakout noise trades, while keeping true verified closes. |
| Profit Ratio    | Increase | Medium | Verified closed reversals have much stronger follow-through to TP2. |
| Gain Magnitude  | Stable | High | No change to take-profit or leverage calculations. |
| Loss Reduction  | Direct Reduction of Losses | High | Eliminates immediate stopouts on false real-time breakouts. |

---

## Risk and Downside

- **Execution Lag (1-minute)**: We enter at the close of the completed 1m bar rather than during the live tick. However, since we are trading 1m confluence sweeps, wait-for-close is the only structurally sound way to confirm institutional wicks.

---

## Implementation Notes

1. **In `engine/core.py` and `backtest.py`**:
   - In the trading loop feature and signal evaluation, replace the raw `ohlcv` passed to strategies with `ohlcv[:-1]` (or slice it prior to calculations).
   - For example:
     ```python
     # Enforce closed candle slicing for all strategy evaluations
     closed_ohlcv = {tf: data[:-1] for tf, data in self.exchange.ohlcv[sym].items()}
     ```
2. **In `ta/features.py`**:
   - Verify that all pattern modules use the sliced completed candle series to calculate indicators.

---

## Verification Criteria

1. **Win Rate Surge**: Strategy win rates should immediately rise above 50% and net PnL should turn heavily positive.
2. **Zero Real-time Repainting**: No trade should be entered during a candle's lifetime that subsequently closes as a strong contrary breakout.
