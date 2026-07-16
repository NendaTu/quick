# Execution Engine & Exchange Drivers

This directory houses the core operational components, execution loops, state-synchronization managers, and physical exchange integration drivers of the Bitget futures bot.

---

## Directory Organization

### 1. `engine/core.py` (The Engine)
- **What it is**: The central nervous system of the bot.
- **Function**: Coordinates the asynchronous execution loops, updates local order book mirrors, polls features, checks strategy triggers, evaluates scoring engine confluence filters, and manages account risk, drawdowns, and graceful shutdowns.
- **Key Methods**:
  - `_trading_loop()`: Asynchronous master loop evaluating and routing trade signals.
  - `_equity_monitor()`: Tracks drawdown boundaries and total ROI limits.
  - `_asset_is_tradable()`: Enforces correlations, book liquidity, and virtual/real-world cooldown lockouts.
  - `_sync_exchange_state()`: Reconciles local positions and pending orders with the exchange upon startup/crash recovery.

### 2. `engine/simulation.py` (The SimulationEngine / Paper Mode)
- **What it is**: Pure simulation execution matching engine.
- **Function**: Mimics real exchange API and order book matching behaviors locally, processing limit order fills, slippage, taker/maker fees, and take-profit/stop-loss OCO triggers on local ticks. Inherits from `Simulator` base class.

### 3. `engine/entry.py` (SignalRouter)
- **What it is**: Direct order dispatching router.
- **Function**: Orchestrates entry and exit dispatch calls, determining the correct payload headers, preset parameters, and triggers for exchange integration.

### 4. `engine/exchanges/` (Exchange Drivers)
This folder contains exchange direct clients.
- `bitget.py`: Fully integrated Bitget exchange client (Live/Demo). Inherits from `DataAcquisitionManager` and `BaseExchange` directly, completely isolating private execution routes from local simulation logic.
- Other drivers (`hyperliquid.py`, `dydx.py`, `mexc.py`, `blofin.py`, `bingx.py`, `coinex.py`): Established placeholder architectures for future regulatory expansions.

---

## Developer Guidelines

### Operational Modes
The bot runs in three modes, configured via `MODE` in `.env`:
1. `"paper"`: Local simulated matching engine, using `SimulationEngine`.
2. `"demo"`: Simulated exchange trading using Bitget's V2 testnet endpoints, utilizing the `"paptrading": "1"` headers and Demo keys.
3. `"live"`: Production exchange trading with real funds on the live Bitget futures exchange.

### Synchronization Standard
To prevent state divergence during server restarts or network disconnects:
- Every mode transition or initialization must call `_sync_exchange_state()`.
- Local open positions and active orders are reconciled directly from the exchange's private endpoints.
- Closed positions must be verified via the Mix Position History endpoints rather than simple local matching.

### Signal Output and Console Logging Standard
To prevent console flooding and ensure consistent output formatting, all strategies must follow these logging guidelines:
- **Setup Discoveries, Setup Steps, and Phase Changes**: These must be logged at `debug` level (e.g. `self.logger.debug`).
- **Signal Details (Entry, SL, TPs, Qty)**: When a setup is discovered, the strategy should log the details at `debug` level, or check the global `LOG_SIGNALS` configuration setting before logging at `info` level.
- **Entries, Fills, and Exits**: These are handled automatically by the matching simulator (`simulator.py`) or exchange layers and printed uniformly via the central `ConsolePublisher` class at `info` level. This guarantees that only signals resulting in actual, successfully routed trades are printed directly to the console.
