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

## Advanced Features

### Configuration Overrides
You can override global `config.py` values by passing a dictionary to the `JBaseStrategy` constructor.
```python
super().__init__(..., config_overrides={"MAX_CONCURRENT_POSITIONS": 5})
```

### Persistence & State Machines
Use the built-in database methods to store and retrieve strategy-specific state. This is essential for complex multi-candle sequences (e.g., Sweep -> BOS1 -> FVG -> BOS2):
- `self.save_state(key, value, simulator)`
- `self.get_state(key, simulator)`

### Scaling & Dynamic Management
The `manage_position` method supports position scaling. For example, to double a position size during a retracement:
```python
return {"action": "double_size"}
```

### Adaptive Learning
The `LearningModel` is available to provide weighted scoring based on collective predictive knowledge. Strategies can utilize this shared "brain" while maintaining their own unique logic filters.

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
