# BASELINE.md — Regression Floor & Baseline Test Run Results

This file records the baseline verification results run on 2026-07-28 before any codebase changes.

## Existing Test Suite

Run Command: `python3 -m pytest`

```
============================= test session starts ==============================
platform linux -- Python 3.12.13, pytest-9.1.1, pluggy-1.6.0
rootdir: /app
plugins: asyncio-1.4.0
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collected 34 items

tools/test_levels.py ................                                    [ 47%]
tools/test_ob_breaker.py .......                                         [ 67%]
tools/test_order_pnl_reconciliation.py ...                               [ 76%]
tools/test_scoring.py ..                                                 [ 82%]
tools/test_symbols.py .                                                  [ 85%]
tools/test_vd_cvd.py .....                                               [100%]

============================== 34 passed in 1.17s ==============================
```

## Bounded Paper-Mode Smoke Run

Attempting a bounded smoke run on `scalper.1.jules`:

We will execute `python3 main.py --strategy scalper.1.jules --mode paper` for a few seconds to verify basic start and initialization cleanly.
