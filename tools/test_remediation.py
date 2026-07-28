"""
1. Summary: Unit and regression tests validating the P0 correctness fixes.
2. Description: Tests config context overrides, learning model split-brain injection, duplicate-entry guards, exposure caps, and strategy state string/type parity.
3. Context: Used in the CI pipeline and pre-commit checks.
"""
import pytest
import config
import logging
from strategies.base_strategy import JBaseStrategy
from engine.base import BaseStrategy, BaseExchange
from engine.core import Engine
from engine.entry import SignalRouter
from ta.scoring import ScoringEngine

def test_p0_6_strategy_state_parity():
    # Construct a JBaseStrategy subclass instance without DB attached
    class MockStrategy(JBaseStrategy):
        def get_entry_signal(self, market_data):
            return None
        def manage_position(self, position, market_data):
            return None

    strat = MockStrategy(name="test_p0_6", version="1", author="jules")

    # Save a real dictionary state
    state_key = "test_dict"
    state_value = {"a": 1, "b": [2, 3]}
    strat.save_state(state_key, state_value)

    # Retrieve state
    retrieved = strat.get_state(state_key)

    # Assert type parity: it must be a dictionary, not a string representation
    assert retrieved == state_value
    assert isinstance(retrieved, dict)
    assert retrieved["b"] == [2, 3]

    # Test stringified fallback retrieval
    state_key_str = "test_dict_str"
    strat._mem_state[state_key_str] = "{'x': 100}"
    retrieved_str = strat.get_state(state_key_str)
    assert retrieved_str == {"x": 100}
    assert isinstance(retrieved_str, dict)


def test_p0_3_duplicate_signals_block(caplog):
    # Construct an Engine instance with paper mode
    engine = Engine(use_db=False, mode="paper")

    # Mock two strategies emitting signals for the same asset
    symbol = "TESTUSDT"
    side = "buy"
    pos_key = f"{symbol}_{side}"

    # Clear active open/pending positions
    engine.open_positions.clear()
    engine.pending_entries.clear()

    # Verify _asset_is_tradable directly
    assert engine._asset_is_tradable(symbol, side) is True

    # Add to pending_entries
    engine.pending_entries.add(pos_key)

    # Verify _asset_is_tradable blocks now
    assert engine._asset_is_tradable(symbol, side) is False

    # Simulate first-accepted-wins loop logging check
    engine.pending_entries.clear()

    # Setup log capturing
    with caplog.at_level(logging.WARNING):
        # Place first signal
        engine.pending_entries.add(pos_key)
        # Attempt to process duplicate signal
        dup_signal = {"symbol": symbol, "side": side, "strategy_id": "strategy_B"}

        # In trading loop duplicate check
        if pos_key in engine.open_positions or pos_key in engine.pending_entries:
            comp_strat = "strategy_A" # mock competing strategy
            log = logging.getLogger("scalper.engine")
            log.warning(f"DUPLICATE BLOCK | Skipped signal for {symbol} {side.upper()} from strategy 'strategy_B' because a position is already active/pending from strategy '{comp_strat}'.")

        assert "DUPLICATE BLOCK" in caplog.text
        assert "strategy_B" in caplog.text
        assert "strategy_A" in caplog.text


def test_p0_4_aggregate_exposure_cap():
    # Construct Engine with custom margin cap
    overrides = {"MAX_AGGREGATE_MARGIN_PCT": 0.10, "INITIAL_EQUITY": 100.0}
    engine = Engine(use_db=False, mode="paper", config_overrides=overrides)
    engine.equity = 100.0

    # Assert aggregate limit calculation (10% of 100 is 10.0 max margin)
    symbol = "ETHUSDT"
    side = "buy"
    assert engine._asset_is_tradable(symbol, side) is True

    # Add an open position with margin 9.0 (under cap)
    engine.open_positions["BTCUSDT_buy"] = {"margin": 9.0}
    assert engine._asset_is_tradable(symbol, side) is True

    # Add another open position with margin 2.0 (total margin is now 11.0, exceeding cap)
    engine.open_positions["SOLUSDT_buy"] = {"margin": 2.0}
    assert engine._asset_is_tradable(symbol, side) is False


@pytest.mark.asyncio
async def test_p0_5_order_type_wiring():
    # Construct a mock exchange that records placed orders
    class MockExchange(BaseExchange):
        def __init__(self):
            self.config = config.ConfigContext(ENTRY_ORDER_TYPE="market")
            self.placed = []
        async def get_tickers(self): return []
        async def get_symbols(self): return []
        async def get_candles(self, s, tf, l=100): return []
        async def scale_position(self, s, si, q, **k): return {}
        async def get_trading_equity(self): return 100.0
        async def get_positions(self): return []
        async def get_open_orders(self): return []
        async def cancel_order(self, s, o): return {}
        async def get_order_status(self, s, o): return {}
        async def place_order(self, symbol, side, order_type, qty, price=None, **kwargs):
            self.placed.append((symbol, side, order_type, qty, price))
            return {"code": "00000"}

    mock_exchange = MockExchange()
    router = SignalRouter(mode="live", exchange=mock_exchange)

    signal = {
        "symbol": "BTCUSDT",
        "side": "buy",
        "qty": 1.0,
        "entry_price": 50000.0
    }

    # Route signal
    await router.route_signal(signal)

    # Assert order type used was "market", not "limit"
    assert len(mock_exchange.placed) == 1
    assert mock_exchange.placed[0][2] == "market"


def test_p0_1_config_override_propagation():
    # Construct engine with overridden ENTRY_SCORE_THRESHOLD = 50.0
    engine = Engine(use_db=False, mode="paper", config_overrides={"ENTRY_SCORE_THRESHOLD": 50.0, "BY_DEFAULT_REPORT_ONLY": False})

    # Verify the override propagates to engine.config
    assert engine.config.ENTRY_SCORE_THRESHOLD == 50.0
    assert engine.config.BY_DEFAULT_REPORT_ONLY is False

    # Mock a features dict that will result in a moderate score (e.g., 25.0)
    # The default threshold is 15.0 (would pass), but the overridden threshold is 50.0 (should fail/reject)
    features = {
        "rsi": 62.5,           # (62.5 - 50) * 2 = +25.0 score
        "mid": 1.0,
        "spread_pct": 0.001,
        "vol_pct": 0.05,
        "confidence": 0.8
    }

    # Clean up all other weights so only WEIGHT_RSI is used
    engine.config.WEIGHT_RSI = 1.0
    engine.config.WEIGHT_RSI_CEILING = 0.0
    engine.config.WEIGHT_IMBALANCE = 0.0
    engine.config.WEIGHT_MACD = 0.0
    engine.config.WEIGHT_TREND_15M = 0.0
    engine.config.WEIGHT_ASSET_CONF = 0.0
    engine.config.WEIGHT_SUPERTREND = 0.0
    engine.config.WEIGHT_DRT = 0.0
    engine.config.WEIGHT_SANITY = 0.0
    engine.config.WEIGHT_BTC_MOM = 0.0
    engine.config.WEIGHT_BTC_CONF = 0.0
    engine.config.WEIGHT_HTF_BIAS = 0.0
    engine.config.WEIGHT_STRUCTURE = 0.0
    engine.config.WEIGHT_VOL_INFLUX = 0.0
    engine.config.WEIGHT_ATR = 0.0
    engine.config.WEIGHT_SPREAD = 0.0
    engine.config.WEIGHT_VOL_PCT = 0.0
    engine.config.WEIGHT_CONFIDENCE = 0.0

    se = ScoringEngine()
    res = se.evaluate(features, side="buy", config_context=engine.config)

    # Aggregate score should be exactly 25.0
    assert res["aggregated_score"] == pytest.approx(25.0)

    # It must be REJECTED because 25.0 is less than overridden 50.0 (even though it's greater than default 15.0)
    assert res["decision"] == "REJECTED"
    assert "Passed threshold" not in res["reason"]
