# BASELINE.md — Regression Floor & Baseline Test Run Results

This file records the baseline verification results run on 2026-07-29 before any new codebase changes.

## Existing Test Suite

Run Command: `python3 -m pytest`

```
============================= test session starts ==============================
platform linux -- Python 3.12.13, pytest-9.1.1, pluggy-1.6.0
rootdir: /app
plugins: asyncio-1.4.0
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collected 39 items

tools/test_levels.py ................                                    [ 41%]
tools/test_ob_breaker.py .......                                         [ 58%]
tools/test_order_pnl_reconciliation.py ...                               [ 66%]
tools/test_remediation.py .....                                          [ 79%]
tools/test_scoring.py ..                                                 [ 84%]
tools/test_symbols.py .                                                  [ 87%]
tools/test_vd_cvd.py .....                                               [100%]

============================== 39 passed in 1.35s ==============================
```

## Bounded Paper-Mode Smoke Run

Executed: `python3 main.py --strategy scalper.1.jules --mode paper` for 1.5 seconds.

### Captured Output:

```
2026-07-29 11:08:04 scalper Loaded Strategy: scalper v1 by jules
2026-07-29 11:08:04 scalper.simulator Initializing metadata...
2026-07-29 11:08:04 scalper.simulator Using cached assets from DB (age: 0.0h)
2026-07-29 11:08:04 scalper.simulator Loaded contract specifications from local cache.
2026-07-29 11:08:04 scalper.simulator Metadata initialized for 251 assets.
2026-07-29 11:08:04 scalper.simulator Starting background data acquisition...
2026-07-29 11:08:04 scalper.engine.loop Dynamic Initialization: 250 assets discovered and loaded.
2026-07-29 11:08:04 scalper.simulator Fetching priority data for BTCUSDT...
2026-07-29 11:08:04 scalper.engine SUMMARY | Equity: 40.00 | ROI: 0.0% | Trades: 0 | Win%: 0.0 (TP: 0.0%) | Open: 0 | Margin: 0.00
2026-07-29 11:08:04 scalper.engine HEARTBEAT | Elapsed: 0h 0m 0s | Loaded: 250/250 (Progress: 0/250) | Pursued: 0 | Abandoned: 0 | Signaled: 0 | PR: 1.00
2026-07-29 11:08:04 scalper.engine.loop Shutdown signal received. Starting graceful exit...
2026-07-29 11:08:04 scalper.engine.loop Shutdown signal received. Waiting for open positions to finalize...
```
