# Core System Documentation

The `main.py` entry point initializes the trading bot for real-time operation in either "Paper" (simulated) or "Live" mode.

## Core Components

### 1. Engine (`engine.py`)
The orchestrator of the system.
- **Position Tracking**: Maintains the `open_positions` map.
- **Trading Loop**: The main `asyncio` loop that updates features, evaluates signals, and triggers execution.
- **Reporting**: Processes fills and exits reported by the exchange layer.

### 2. Simulator (`simulator.py`)
A high-fidelity exchange simulation layer used in `paper` mode.
- **Matching Engine**: Simulates Limit and Market orders against a synthetic order book.
- **Data Feed**: Handles WebSocket callbacks and converts raw trade data into OHLCV candles.
- **TA Suite**: The `get_features` method serves as the central hub for all technical analysis from `ta/`.

### 3. Models (`models.py`)
The decision-making layer.
- **LearningModel**: Scores market opportunities based on weights and feature thresholds.
- **Signal Logic**: Calculates the precise entry, stop, and take-profit prices for every trade.

## Operational Lifecycle

1. **Initialization**: Loads `.env`, validates `config.py`, and initializes the `Engine`.
2. **Warm-up**: Fetches the last 500-1000 candles for all tracked assets to populate indicator history.
3. **Data Feed**: Starts WebSocket tasks to receive real-time Ticks and Order Book snapshots.
4. **Maintenance**: Periodically purges old DB data and recalculates asset correlations.
5. **Shutdown**: Catches `SIGINT` (Ctrl+C) to wait for open positions to finalize or stop gracefully.

## Database Integration
The system uses a shared SQLite database (`market_data.db`) for:
- Persisting historical candles.
- Logging trade signals (JSON payload).
- Internal audit logs for performance analysis.
