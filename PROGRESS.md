# PROGRESS.md — Remediation & Modularization Progress Log

This document tracks all changes made during the remediation and modularization of the repository, as directed by `AGENTS.md`.

## Summary & Current Status
- **Current Phase:** Phase 1 (Backlog Loop) in progress.
- **Completed Items:**
  - §9.1 and §9.2 of AGENTS.md.
  - Setup Baseline testing and verified `.env` is gitignored.
  - Recorded a full paper-mode smoke run on `scalper.1.jules`.
  - Configured `pytest` and verified all 39 existing tests pass.
  - Retroactively documented all Round 1 completed backlog items.

---

## [Phase 0] Retroactive Backlog Logging (Round 1)
*Date: 2026-07-28 (retroactive, written 2026-07-29)*

The following items were completed during Round 1 but were not individually logged in `PROGRESS.md` before this session:

### **P0-1 — Configuration Override Propagation**
* **Files touched:** `config/__init__.py`, `engine/core.py`, `main.py`, `compare.py`
* **What changed:** Replaced `setattr` mutation on the bare config module with localized instantiation of an immutable `ConfigContext` in each engine setup. Downstream components now receive the config context explicitly.
* **Why:** To ensure thread/process-isolated configuration values do not pollute global settings.
* **Behavior change?** Yes. Downstream classes now read configuration via context variables instead of global variables.

### **P0-2 — Model Split-Brain Prevention**
* **Files touched:** `engine/core.py`, `main.py`, `compare.py`
* **What changed:** Shared a single `LearningModel` instance via constructor injection (`model=engine.model`) across strategies rather than letting them construct independent private models.
* **Why:** To guarantee that reinforcement learning is centralized and synchronized.
* **Behavior change?** Yes. All strategy instances now use a single synchronized learning model.

### **P0-3 — Duplicate Entry Prevention**
* **Files touched:** `engine/loop.py`
* **What changed:** Implemented an atomic `pending_entries` reservation synchronously within the main execution loop before invoking any asynchronous requests.
* **Why:** To prevent racing entry triggers from launching duplicate orders on the same asset.
* **Behavior change?** Yes. Duplicate entry triggers on the same asset are blocked atomically.

### **P0-4 — Aggregate Exposure Cap**
* **Files touched:** `engine/risk.py`, `config/settings.py`
* **What changed:** Enforced `MAX_AGGREGATE_MARGIN_PCT=0.10` and `MAX_CONCURRENT_POSITIONS=15` limits during asset tradability evaluation.
* **Why:** To restrict the total margin risk profile and position concentration across the portfolio.
* **Behavior change?** Yes. Trading is capped if aggregated margin exposure exceeds 10% of total equity.

### **P0-5-partial — Order Type Wiring (Entry Path)**
* **Files touched:** `engine/exchanges/bitget.py`, `engine/entry.py`
* **What changed:** Routed entry orders through the configured `ENTRY_ORDER_TYPE` parameter instead of hardcoding market orders.
* **Why:** To allow configurable limit vs. market entries.
* **Behavior change?** Yes.

### **P0-6 — Strategy State Parity**
* **Files touched:** `strategies/base_strategy.py`
* **What changed:** Stored strategy memory state natively as original dictionary structures rather than stringified representation fallbacks.
* **Why:** To prevent JSON encoding and string formatting mismatch bugs during runtime recovery.
* **Behavior change?** Yes.

### **P0-7 — Simulator Wiring Contract**
* **Files touched:** `strategies/base_strategy.py`, `engine/core.py`
* **What changed:** Added loud assertions during strategy initialization confirming that the simulator wrapper has been correctly injected and warmed up.
* **Why:** To prevent silent start freezes caused by un-wired simulator instances.
* **Behavior change?** Yes.

### **P1-1 — God-Object Decomposition**
* **Files touched:** `engine/core.py`, `engine/positions.py`, `engine/risk.py`, `engine/reporting.py`, `engine/regimes.py`, `engine/reconciliation.py`, `engine/loop.py`
* **What changed:** Extracted the massive `Engine` class into modular single-concern components: `PositionLedger`, `RiskGate`, `TradeReporter`, `RegimeClassifier`, `ExchangeSync`, and `TradingLoop`. Preserved properties on `Engine` for backward compatibility.
* **Why:** To make the architecture maintainable, readable, and testable.
* **Behavior change?** No (fully backward-compatible properties exposed on `Engine`).

### **P1-2-partial — Config Package Modularization**
* **Files touched:** `config/__init__.py`, `config/settings.py`
* **What changed:** Migrated flat configurations to structured domain settings classes utilizing Pydantic models.
* **Why:** To organize configuration settings logically.
* **Behavior change?** No.

### **P1-5 — WebSocket Callback Placement**
* **Files touched:** `simulator.py`
* **What changed:** Moved `_ws_callback` inside the `DataAcquisitionManager` class.
* **Why:** To standardize live data streams and historical tick backfills.
* **Behavior change?** No.

### **P1-6 — Virtual Cooldown System**
* **Files touched:** `engine/risk.py`
* **What changed:** Programmed re-entry and exit cooldown validations to check simulated timestamps instead of real system time.
* **Why:** To ensure backtest cooldown frequencies mirror physical time scales.
* **Behavior change?** Yes.

### **P2-3 — Remove Double-Counting Asset Confidence Weight**
* **Files touched:** `ta/scoring.py`, `config/settings.py`
* **What changed:** Removed the redundant `asset_conf` double-counting variable and its corresponding weight configuration.
* **Why:** To prevent mathematical skew during entry scoring evaluation.
* **Behavior change?** Yes.

### **P2-11 — Transient Database Isolation**
* **Files touched:** `config/__init__.py`, `compare.py`
* **What changed:** Enforced mode-aware SQLite paths (`market_data_{mode}.db`) and utilized transient in-memory databases (`:memory:`) during data warming up phases.
* **Why:** To eliminate concurrent write/read lock-contention locks.
* **Behavior change?** Yes.

### **P2-15 — Placeholder Headers**
* **Files touched:** `engine/exchanges/*.py`
* **What changed:** Added explicit 3-part standardization comments to all placeholder exchange stubs.
* **Why:** To make the stubs programmatically discoverable and confirm they are placeholders.
* **Behavior change?** No.

---

## [Phase 0] Baseline Verification
*Date: 2026-07-29*

### **Verification Tasks:**
1. Installed base dependencies and newly declared packages (`pydantic==2.13.4`, `pydantic-settings==2.14.2`, `pytest==9.1.1`, `pytest-asyncio==1.4.0`) inside a clean virtual environment.
2. Ran `python3 -m pytest` and verified 100% of the 39 tests passed without issue.
3. Successfully ran `main.py`, `backtest.py`, and `compare.py` import checks to confirm zero syntax/module errors.
4. Executed a bounded paper-mode smoke run of `scalper.1.jules` on BTCUSDT, validating that initial metadata, contract specs, and historical requirements loaded and exited cleanly.
5. Confirmed `.env` is gitignored.

---

## [Phase 1] Backlog Loop (Round 2)

### **R0-1 — Add Missing Core Dependencies to requirements.txt**
* **Date:** 2026-07-29
* **Files touched:** `requirements.txt`
* **What changed:** Formally declared and pinned exact versions of `pydantic==2.13.4`, `pydantic-settings==2.14.2`, `pytest==9.1.1`, and `pytest-asyncio==1.4.0` in `requirements.txt`.
* **Why:** To prevent a fatal import regression where the application could not run from a fresh checkout due to undeclared dependencies that were introduced during the config migration.
* **Behavior change?** Yes. The application now successfully runs, imports, and tests properly from a clean environment setup.
* **How verified:** Installed inside a clean environment and confirmed `python3 -m pytest` and imports (`main`, `backtest`, `compare`) pass with zero manual intervention.

### **R0-2 — TP/SL Order Fee Estimation Correction**
* **Date:** 2026-07-29
* **Files touched:** `config/settings.py`, `engine/exchanges/bitget.py`, `tools/test_remediation.py`
* **What changed:**
  - Updated `engine/exchanges/bitget.py`'s `place_order` fee-vs-profit check to always assume taker fees (`self.config.TAKER_FEE`) for the exit leg.
  - Hardcoded and documented stop-loss (SL) as market-only by design for robust risk management.
  - Added test `test_r0_2_exit_fee_rate_uses_taker` in `tools/test_remediation.py` verifying that narrow profit targets which would erroneously pass if maker fees were assumed are correctly rejected with taker fees.
* **Why:** On live/demo Bitget, take-profits and stop-losses execute as market/taker orders. Consulting `TP_ORDER_TYPE == "limit"` caused a correctness bug where the fee-vs-profit filter used an overly optimistic maker fee assumption, letting through narrow fee trap trades that would lose money in reality.
* **Behavior change?** Yes. Exit fee estimation for live/demo Bitget always reflects real taker-fee execution, and narrow fee traps are accurately rejected.
* **How verified:** Added robust regression unit test `test_r0_2_exit_fee_rate_uses_taker` which checks that narrow margin profits are rejected under the new taker-fee estimation. Ran `pytest` and verified all tests pass.

### **R0-3 — Duplicate Entry Guard Regression Test Rewrite**
* **Date:** 2026-07-29
* **Files touched:** `tools/test_remediation.py`
* **What changed:** Rewrote `test_p0_3_duplicate_signals_block` in `tools/test_remediation.py` to construct a real `Engine` with its real `TradingLoop`, mock strategies, simulated assets, and run the actual production `_trading_loop()` check. Used a selective `asyncio.sleep` bypass of the initial loop cooldown to let the loop spin instantly.
* **Why:** The previous test implemented its own duplicate warning block inline, verifying nothing from production code. If the duplicate check were completely deleted from `engine/loop.py`, the old test would still pass.
* **Behavior change?** No.
* **How verified:** Ran `pytest` and confirmed that the rewritten test passes successfully. Verified that if the duplicate block check is commented out in `engine/loop.py`, this new test fails as expected.

### **R0-4 — backtest.py Shared Model Injection Refactor**
* **Date:** 2026-07-29
* **Files touched:** `backtest.py`
* **What changed:** Refactored `backtest.py`'s strategy loading pathways inside `run_backtest` and `run_backtest_portfolio` to directly inject the shared learning model (`model=engine.model`) via `StrategyWrapper._load_strategy(...)` parameters. Completely deleted the `self.simulator.engine.model` back-reference lookup.
* **Why:** The back-reference pattern violates layering guidelines by forcing the simulation layer to fetch private ownership details, which also causes split-brain issues in environments where `engine` is not set (e.g. lightweight TA backtesting).
* **Behavior change?** Yes. All strategy instances in backtesting now cleanly receive the shared model explicitly through the initialization pipeline.
* **How verified:** Ran `pytest` to confirm zero regression or syntax errors, and successfully imported `backtest.py`.

### **R1-1 — TradeReporter & PositionLedger Interfaces Refactor**
* **Date:** 2026-07-29
* **Files touched:** `engine/core.py`, `engine/loop.py`, `engine/positions.py`, `engine/reporting.py`, `engine/reconciliation.py`, `engine/exchanges/bitget.py`, `tools/test_remediation.py`
* **What changed:**
  - Refactored `TradeReporter` to act as an active, single-concern state tracker and added public standalone `record_entry` and `record_exit` methods. All database persistence is decoupled and managed at the orchestrator level.
  - Added formal public interfaces `is_open`, `is_pending`, `get_open_keys`, `get_pending_keys`, and `get_all_positions` on `PositionLedger`.
  - Audited and rewrote all collection lookups/mutations on `self.ledger.open_positions` and `self.ledger.pending_entries` inside `engine/core.py`, `engine/loop.py`, `engine/reconciliation.py`, and `engine/exchanges/bitget.py` to route strictly through these clean public interfaces.
  - Added standalone unit tests for `TradeReporter`'s stats aggregation in `tools/test_remediation.py`.
* **Why:** To complete Phase 1 god-object decomposition (P1-1). `Engine` previously owned extensive statistics-tracking logic, and code outside `PositionLedger` directly mutated internal collection dictionaries and sets.
* **Behavior change?** No. Settle trade arithmetic, compounding logic, and overall system functionality remain identical but with a cleaner, highly modular design.
* **How verified:** Grepped the `engine/` package and verified that no direct collection reads/mutations remain outside `engine/positions.py`. Ran the full test suite (now 41 tests) and verified that all tests, including the new `test_trade_reporter_standalone`, pass flawlessly.


### **R1-3 — Formalize ABC Contracts & Eliminate Duck-Typing**
* **Date:** 2026-07-29
* **Files touched:** `engine/base.py`, `engine/simulation.py`, `engine/exchanges/bitget.py`, `engine/core.py`, `engine/loop.py`
* **What changed:**
  - Formalized all required and optional attributes/methods inside `BaseExchange` and `BaseStrategy` abstract base classes.
  - Declared `last_price`, `ohlcv`, `books`, `db`, `ready_assets`, `used_margin`, `symbol_map`, `rev_symbol_map`, and `asset_correlations` natively inside `BaseExchange.__init__`.
  - Declared `name`, `strategy_id`, `params`, `is_ready()`, and `get_readiness_eta()` inside `BaseStrategy`.
  - Audited and eliminated all defensive `hasattr`/`getattr` duck-typing checks on exchanges and strategies across `TradingLoop`, `Engine`, and `RiskGate`, replacing them with type-safe direct calls.
* **Why:** The previous architecture used untyped defensive duck-typing checks throughout core execution layers, which bypassed static analysis and made interface contracts fragile.
* **Behavior change?** No.
* **How verified:** Ran the entire test suite and verified that 100% of the tests pass perfectly.

### **R1-4 — Wire OrderRequest Payload Standardization**
* **Date:** 2026-07-29
* **Files touched:** `engine/entry.py`, `engine/loop.py`, `strategies/scalper.1.jules.py`, `tests/test_remediation.py`
* **What changed:**
  - Integrated `OrderRequest` inside `SignalRouter.route_signal` by accepting both dictionaries and `OrderRequest` instances, standardizing on properties instead of manual `kwargs.pop` popping.
  - Refactored `ScalperStrategy`'s `get_entry_signal` inside `strategies/scalper.1.jules.py` to construct and return a typed `OrderRequest` instead of a bare dictionary.
  - Updated `TradingLoop._trading_loop()` in `engine/loop.py` to support `OrderRequest` returns from strategies by safely converting them to dict when mutating.
  - Added test `test_order_request_routing_and_safety` in `tests/test_remediation.py` verifying identical routing behavior and type-safe parameter collision protection.
* **Why:** The previous codebase defined the `OrderRequest` payload but never used it, relying on fragile string popping throughout execution routers.
* **Behavior change?** No (fully backward-compatible and maps to identical execution).
* **How verified:** Ran `pytest` and confirmed that 100% of the tests pass flawlessly.

### **R3-1, P3-1, P3-2, P3-3 — Testing & Verification Infrastructure**
* **Date:** 2026-07-29
* **Files touched:** `tests/test_exchange_sync.py`, `tests/test_smoke_run.py`, `.github/workflows/run_tests.yml`, `engine/base.py`, `engine/simulation.py`
* **What changed:**
  - Created a dedicated unit test suite for `ExchangeSync` state reconciliation (`tests/test_exchange_sync.py`) verifying position synchronisation, fallback exit calculations, order tracking, and trigger orders reconciliation.
  - Established a clean `tests/` tree and migrated all unit and integration tests from `tools/` into it (preserving financial correctness).
  - Programmed and codified a local network-free paper-mode smoke test (`tests/test_smoke_run.py`) for `ScalperStrategy` that verifies execution loops, WS updates, and graceful finalization with zero real API calls.
  - Added unified asynchronous `close` teardown handlers across `BaseExchange` and `SimulationEngine` to cleanly finalize client sessions.
  - Configured a standard, automated GitHub Actions workflow (`.github/workflows/run_tests.yml`) to install packages and run the test suite on push and pull requests on all branches.
* **Why:** The repository had no unified testing tree (`tests/` directory), lacked automated CI pipelines, had zero dedicated tests for critical state reconciliation math, and lacked an asserted codified paper smoke test.
* **Behavior change?** No.
* **How verified:** Ran the unified test suite (now 48 tests) and verified that 100% of the tests pass flawlessly.
