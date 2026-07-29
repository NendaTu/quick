"""
1. Summary: Codified paper-mode smoke test for the ScalperStrategy.
2. Description: Runs a bounded, local, network-free paper simulation run of ScalperStrategy, verifying correct initialization, order book updates, trading loop execution, and graceful finalization.
3. Context: Regression protection ensuring the live trading loops and matching simulator remain functional.
"""
import asyncio
import time
import pytest
import importlib.util
from engine.core import Engine

@pytest.mark.asyncio
async def test_paper_mode_smoke_run():
    # Load ScalperStrategy dynamically to avoid Python import syntax limitations (numeric dot segments)
    spec = importlib.util.spec_from_file_location("scalper_strategy", "strategies/scalper.1.jules.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    ScalperStrategy = module.ScalperStrategy

    # 1. Setup minimal local preloaded data to avoid any real network requests
    now_ts = time.time()
    preloaded_data = {
        "discovered_assets": ["BTCUSDT"],
        "contract_specs": {
            "BTCUSDT": {
                "symbol": "BTCUSDT",
                "pricePlace": "2",
                "volumePlace": "3",
                "minTradeUSDT": "5",
                "maxLever": "20"
            }
        },
        "leverage_limits": {"BTCUSDT": 20.0},
        "ohlcv": {
            "BTCUSDT": {
                "1m": [
                    {"ts": now_ts - 120, "o": 50000.0, "h": 50100.0, "l": 49900.0, "c": 50050.0, "v": 1.5},
                    {"ts": now_ts - 60, "o": 50050.0, "h": 50150.0, "l": 50000.0, "c": 50100.0, "v": 2.0}
                ]
            },
            "BTCUSDT_BTCUSDT": {} # handle potential fallback
        },
        "confluence_history": {
            "BTCUSDT": {
                "15m": [50100.0], "1H": [50100.0], "4H": [50100.0], "1D": [50100.0], "1W": [50100.0]
            }
        },
        "last_candle_ts": {"BTCUSDT": {"1m": now_ts - 60}},
        "last_price": {"BTCUSDT": 50100.0}
    }

    # Also add BTC_SYMBOL confluence data to make sure no KeyError is raised
    from config import BTC_SYMBOL
    preloaded_data["ohlcv"][BTC_SYMBOL] = {
        "1m": [
            {"ts": now_ts - 120, "o": 50000.0, "h": 50100.0, "l": 49900.0, "c": 50050.0, "v": 1.5},
            {"ts": now_ts - 60, "o": 50050.0, "h": 50150.0, "l": 50000.0, "c": 50100.0, "v": 2.0}
        ]
    }
    preloaded_data["confluence_history"][BTC_SYMBOL] = {
        "15m": [50100.0], "1H": [50100.0], "4H": [50100.0], "1D": [50100.0], "1W": [50100.0]
    }
    preloaded_data["last_candle_ts"][BTC_SYMBOL] = {"1m": now_ts - 60}
    preloaded_data["last_price"][BTC_SYMBOL] = 50100.0

    # 2. Instantiate Engine with custom paper mode overrides
    overrides = {
        "USE_VIRTUAL_BALANCE": True,
        "INITIAL_EQUITY": 100.0,
        "RISK_PER_TRADE": 0.01,
        "SHOW_HEARTBEAT": False,
        "SHOW_PERIODIC_SUMMARY": False
    }
    engine = Engine(use_db=False, mode="paper", config_overrides=overrides)

    # 3. Instantiate and wire ScalperStrategy
    strategy = ScalperStrategy(simulator=engine.exchange, model=engine.model)
    engine.strategy = strategy
    engine.strategies = [strategy]

    # 4. Start the engine in the background
    start_task = asyncio.create_task(engine.start(preloaded_data=preloaded_data))

    # Wait for the loop to spin up
    await asyncio.sleep(0.5)

    # 5. Feed a public trade update to mock WebSocket book and price tick
    mock_ws_msg = {
        "arg": {"channel": "books15", "instId": "BTCUSDT"},
        "data": [{
            "bids": [["50100.0", "1.5"]],
            "asks": [["50105.0", "2.0"]],
            "ts": str(int(now_ts * 1000))
        }]
    }
    res = engine.exchange._ws_callback(mock_ws_msg)
    if asyncio.iscoroutine(res):
        await res

    # Let the loop execute a tick
    await asyncio.sleep(0.5)

    # 6. Request graceful shutdown
    engine.stop_event.set()

    # Wait for engine to terminate cleanly
    await asyncio.wait_for(start_task, timeout=5.0)

    # Clean up client sessions to prevent Unclosed client session warnings (R2-2)
    await engine.exchange.close()

    # 7. Sane assertions on results
    assert engine.equity == 100.0
    assert engine.total_trades == 0
    assert engine.session_signals >= 0
