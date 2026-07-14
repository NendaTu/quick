# Technical Analysis (TA) & Patterns Engine

This directory contains the core mathematical, analytical, and indicator processing sub-systems of the Bitget Trading Bot. All indicator calculations and market patterns are designed to be completely **stateless and decoupled** from the order execution engine to prevent repainting and look-ahead bias.

---

## Directory Organization

### 1. `ta/scoring.py` (Unified Scoring Engine)
- **What it is**: The centralized stateless decision evaluator.
- **Function**: Converts 18 distinct directional and quality indicators into raw scores (-100 to +100), applies user-defined static config weights and adaptive dynamic learning weights, and aggregates them into a normalized weighted average score.
- **Usage**:
  ```python
  from ta.scoring import ScoringEngine
  se = ScoringEngine()
  scoring_result = se.evaluate(features, side="buy", config_context=config)
  ```

### 2. `ta/features.py` (Stateless Feature Extraction)
- **What it is**: The master data compiler.
- **Function**: Pulls raw OHLCV candle streams, order book books, and tick history, and outputs a flat dictionary of calculated indicators (RSI, ADX, MACD, DRT, etc.) for both backtesters and live websocket loops.

### 3. `ta/indicators/` (Core Math & Indicators)
Contains pure mathematical implementations of technical indicators:
- `rsi.py`: Relative Strength Index calculations.
- `macd.py`: Moving Average Convergence Divergence lines and histogram.
- `supertrend.py`: Supertrend indicator with ATR-channel bands.
- `atr.py`: Average True Range for volatility-aware stops and targets.
- `adx.py`: Average Directional Index for trend-strength detection.
- `ema.py`: Exponential Moving Average calculations.
- `book_delta.py` & `flow.py`: Limit order book queue depth imbalance and deltas.

### 4. `ta/patterns/` (SMC and Market Structure Patterns)
Implements Institutional / Smart Money Concepts (SMC) structure detection:
- `structure.py`: Break of Structure (BOS) and Market Structure Shift (MSS).
- `fvg.py`: Fair Value Gap detection (anchored to closed candles to avoid repainting).
- `sessions.py`: Centralized ICT Session/Killzone boundary mapping and checking logic.
- `drt.py`: Directional Trend linear regression slope squashed via Sigmoids.
- `swings.py`: High-fidelity local price swing peak and valley detection.
- `poi.py` & `liquidity.py`: Point of Interest and buy-side/sell-side liquidity pools.

### 5. `ta/candles/` (Candle Sentiment Pattern Matching)
- `engulfing.py` & `engulfing_total.py`: Classic and composite bullish/bearish engulfing patterns.
- `sentiment.py`: Multi-candle buying/selling pressure sentiment index.

---

## Developer Guidelines

1. **Keep Calculations Stateless**: Never maintain local states (such as active positions or order tracking) inside `ta/` modules. Always pass the raw historical data lists (e.g. `ohlcv_data` or `book`) as parameters.
2. **Prevent Look-ahead Bias**: For any indicator that looks at historical bars, always slice the list up to the second-to-last element (`ohlcv[:-1]`) if you are evaluating close signals on the current open bar.
3. **Handle Missing Data Gracefully**: Always add fallbacks or defaults (e.g., returning 0.0 or neutral 50.0) when the requested warm-up history is insufficient to compute an indicator.
