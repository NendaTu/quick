# Strategy Development Guide

This directory contains the **orchestrators** of the Bitget Futures Trading Bot. A strategy file defines the complete, ordered sequence of conditions, filters, and decisions required to execute a full trade exercise.

## Naming Convention

All strategy files must follow the strict naming convention:
`[strategy-name].[version].[author].py`

Example: `scalper.1.jules.py`

## Strategy Standards

Every strategy file must be self-contained and adhere to the following standards:

### 1. Mandatory Header Documentation
The top of every strategy file must contain an exhaustively comprehensive narrative description in a multi-line docstring. This is non-negotiable.

#### Mandatory Comment Sections:
- **Overview**: A high-level explanation of the strategy's logic and the market conditions it targets.
- **Goals**: Expected ROI/ROE per trade, target trade frequency, and the rationale behind the win-rate/RRR targets.
- **Modules Used**: A list of every `ta/` or utility module imported, explaining exactly what role each plays in the decision sequence.
- **The Intended Flow**: A step-by-step walkthrough of the logic from initial market data polling to entry signal, through position management, and finally to exit.
- **Limitations & Assumptions**: Known conditions under which the strategy is expected to underperform (e.g., low volatility, high slippage assets, specific session behaviors).

#### Header Comment Template:
```python
"""
# [Strategy Name] Strategy v[Version].[Author]

## Overview
This strategy [detailed description of logic...].
It is designed for [market conditions...] using [timeframes...].

## Goals
- Target ROE: [e.g., 20% per trade]
- Frequency: [e.g., 10-20 trades per hour]
- Rationale: [e.g., High-frequency micro-compounding...]

## Modules Used
- `ta/patterns/sessions.py`: Used to identify [specific role...]
- `ta/indicators/rsi.py`: Provides [specific filter...]
- ...

## The Intended Flow
1. [Step 1: e.g., Identify HTF Bias...]
2. [Step 2: e.g., Monitor for LTF liquidity sweep...]
3. [Step 3: e.g., Confirm entry via BOS and FVG retest...]
4. [Step 4: e.g., Manage position with trailing stops...]

## Limitations & Assumptions
- Assumes [e.g., 0.1% slippage maximum]
- May underperform during [e.g., news events, bank holidays]
"""
```

### 2. Technical Requirements
- **Inheritance**: Must inherit from `JBaseStrategy` (found in `strategies/base_strategy.py`).
- **Class Name**: Should contain the word `Strategy` (e.g., `ScalperStrategy`).
- **Initialization**: Should accept `config_overrides` and `simulator`.

### 3. Core Interface
Strategies must implement (or explicitly delegate) the following methods:

#### `get_entry_signal(self, market_data: Dict) -> Optional[Dict]`
- **Called**: Every tick for every enabled asset.
- **Input**: `market_data` contains `symbol`, `book`, `equity`, and `features`.
- **Output**: Returns a dictionary with `side`, `entry_price`, `stop_price`, `exit_price`, and `qty` if a trade should be opened. Returns `None` otherwise.

#### `manage_position(self, position: Dict, market_data: Dict) -> Optional[Dict]`
- **Called**: Every tick for every open position.
- **Input**: Current `position` data and latest `market_data`.
- **Output**: Can return updates (e.g., new SL/TP levels) or an exit signal. Return `None` to maintain status quo.

### 4. Backtest Deliverables & Output Logging Standard
Every strategy file must support clean offline auditing and consistent sandbox output verification. All running strategies are required to produce and populate three specific assets:
1. **Confluence Metrics Log**: The strategy must cleanly trigger external metrics logging in `docs/temp/[timestamp].metrics-log.txt` showing continuous directional scores on every signal evaluation.
2. **Captured Console Output**: The runtime execution logs of the strategy backtest must cleanly tee standard outputs to `docs/temp/console-log.txt`.
3. **Specs Cache**: The strategy backtest routine must automatically create and update the local specifications cache file in `docs/temp/contract_specs_cache.json` on execution.

## Advanced Features & Architectural Guardrails

### 1. Unified Scoring Engine Confluence Check
All strategies can leverage or are automatically gated by the central `ScoringEngine`.
- Before an entry is executed, the Engine automatically extracts features and scores them continuously from `-100` (max bearish) to `+100` (max bullish).
- If the final aggregate score fails to meet the `ENTRY_SCORE_THRESHOLD` (default `15.0`), the signal is safely rejected as a low-confluence setup.
- If a strategy needs custom indicators or custom weights, it can pass an `overrides` dictionary to bypass specific indicator filters.

### 2. "Zombie Sweep" Prevention
In high-frequency sweep-reversal strategies, there is a risk that after a successful trade and virtual cooldown expiration, the same historical sweep is detected again and entered repeatedly ("Zombie Sweep").
To prevent this clobbering loop:
- **Phase 7 (Entry)**: Save the active sweep timestamp:
  ```python
  self.save_state(f"{symbol}_last_traded_sweep_ts", sweep_ts, self.simulator)
  ```
- **Phase 3 (Detection)**: Retrieve the last traded sweep time and strictly block duplicate entries on historical wicks:
  ```python
  last_traded_sweep = self.get_state(f"{symbol}_last_traded_sweep_ts", self.simulator)
  if last_traded_sweep is not None and sweep_ts <= float(last_traded_sweep):
      return None
  ```

### 3. Minimum Stop-Loss Distance (Breathing Room)
Always de-hardcode tight minimum stops (like 0.1%) to avoid immediate stop-outs on spread wiggles. Ensure stops are dynamically protected by the central `SL_MOVE` (0.4%) configuration parameter:
```python
min_stop_dist = entry_price * getattr(config, "SL_MOVE", 0.004)
if abs(entry_price - stop_price) < min_stop_dist:
    stop_price = entry_price - (min_stop_dist if sweep_side == 'ssl' else -min_stop_dist)
```

---

## Strategy Template

```python
"""
# [Strategy Name] Strategy v[Version].[Author]

## Overview
This strategy [detailed description of logic...].
It is designed for [market conditions...] using [timeframes...].

## Goals
- Target ROE: [e.g., 20% per trade]
- Frequency: [e.g., 10-20 trades per hour]
- Rationale: [e.g., High-frequency micro-compounding...]

## Modules Used
- `ta/patterns/sessions.py`: Used to identify [specific role...]
- `ta/indicators/rsi.py`: Provides [specific filter...]
- ...

## The Intended Flow
1. [Step 1: e.g., Identify HTF Bias...]
2. [Step 2: e.g., Monitor for LTF liquidity sweep...]
3. [Step 3: e.g., Confirm entry via BOS and FVG retest...]
4. [Step 4: e.g., Manage position with trailing stops...]

## Limitations & Assumptions
- Assumes [e.g., 0.1% slippage maximum]
- May underperform during [e.g., news events, bank holidays]
"""
from strategies.base_strategy import JBaseStrategy
import config

class MyNewStrategy(JBaseStrategy):
    def __init__(self, config_overrides=None, simulator=None):
        super().__init__(
            name="my_new_strat",
            version="1",
            author="dev",
            config_overrides=config_overrides
        )
        self.simulator = simulator

    def get_entry_signal(self, market_data):
        # Your entry logic here
        pass

    def manage_position(self, position, market_data):
        # Your management logic here
        pass
```
