"""
1. Summary: Unit and regression tests validating the P0 correctness fixes.
2. Description: Tests config context overrides, learning model split-brain injection, duplicate-entry guards, exposure caps, and strategy state string/type parity.
3. Context: Used in the CI pipeline and pre-commit checks.
"""
import pytest
import config
import logging
import asyncio
from strategies.base_strategy import JBaseStrategy
from engine.base import BaseStrategy, BaseExchange
from engine.core import Engine
from engine.entry import SignalRouter
from ta.scoring import ScoringEngine
from unittest.mock import AsyncMock, patch, MagicMock
from engine.exchanges.bitget import BitgetExchange

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


@pytest.mark.asyncio
async def test_p0_3_duplicate_signals_block(caplog):
    # Construct an Engine instance with paper mode
    engine = Engine(use_db=False, mode="paper")

    # Mock the assets and books
    symbol = "TESTUSDT"
    side = "buy"
    pos_key = f"{symbol}_{side}"

    engine.enabled_assets = [symbol]

    from orderbook import OrderBook
    engine.books[symbol] = OrderBook(symbol)
    engine.books[symbol].update([[100.0, 1.0]], [[100.1, 1.0]])
    engine.books[config.BTC_SYMBOL] = OrderBook(config.BTC_SYMBOL)
    engine.books[config.BTC_SYMBOL].update([[50000.0, 1.0]], [[50000.1, 1.0]])

    exchange = engine.exchange
    exchange.ready_assets = {symbol, config.BTC_SYMBOL}
    exchange.get_features = MagicMock(return_value={
        "rsi": 50.0, "mid": 100.0, "spread_pct": 0.001, "vol_pct": 0.05, "confidence": 0.8,
        "btc_1D": 0.0, "btc_4H": 0.0, "btc_1H": 0.0, "btc_15m": 0.0
    })

    class MockStrategy:
        def __init__(self, name):
            self.name = name
            self.strategy_id = name
            self.params = {}
        def is_ready(self, symbol):
            return True
        def get_entry_signal(self, market_data):
            return {"symbol": symbol, "side": side, "qty": 1.0, "entry_price": 100.0, "stop_price": 95.0, "exit_price": 105.0}

    engine.strategies = [MockStrategy("strategy_B")]

    # Pre-populate pending_entries
    engine.ledger.clear()
    engine.ledger.add_pending(pos_key)

    # Setup log capturing
    original_sleep = asyncio.sleep
    async def mock_sleep(seconds, *args, **kwargs):
        if seconds == 5:
            await original_sleep(0.01)
        else:
            await original_sleep(seconds)

    with caplog.at_level(logging.WARNING), \
         patch("asyncio.sleep", side_effect=mock_sleep):
        # Run the trading loop for a brief moment and let it time out
        try:
            await asyncio.wait_for(engine.loop._trading_loop(), timeout=0.2)
        except asyncio.TimeoutError:
            pass

        assert "DUPLICATE BLOCK" in caplog.text
        assert "strategy_B" in caplog.text
        assert "pending" in caplog.text


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


@pytest.mark.asyncio
async def test_r0_2_exit_fee_rate_uses_taker():
    # Patch to avoid actual network / sync_time during initialization
    with patch("engine.exchanges.bitget.BitGetWSClient"), \
         patch("bitget_client.BitGetClient.sync_time", new_callable=AsyncMock), \
         patch("bitget_client.BitGetClient.place_order", new_callable=AsyncMock) as mock_place_exec:

        mock_place_exec.return_value = {"code": "00000", "msg": "unexpected success"}

        # Initialize BitgetExchange
        exchange = BitgetExchange(
            api_key="mock_key",
            secret_key="mock_secret",
            passphrase="mock_passphrase",
            is_demo=True
        )

        # Ensure leverage and margin mode calls are mocked
        exchange.set_margin_mode = AsyncMock(return_value={"code": "00000"})
        exchange.set_leverage = AsyncMock(return_value={"code": "00000"})

        # Configure ConfigContext to ensure we have standard MAKER_FEE, TAKER_FEE, etc.
        exchange.config.MAKER_FEE = 0.0002
        exchange.config.TAKER_FEE = 0.0006
        exchange.config.MIN_NET_TP_PROFIT_PCT = 0.001

        # Set self.last_price
        exchange.last_price["BTCUSDT"] = 100.0

        # Now place a limit entry order with tight TP that would clear with maker fee but fails with taker fee.
        # entry = 100.0, exit = 100.05, qty = 1.0, order_type = "limit"
        # Since exit_fee_rate uses TAKER_FEE (0.0006), it will fail.
        # If it used TP_ORDER_TYPE = "limit" -> MAKER_FEE (0.0002), it would pass.
        # Let's verify that even with TP_ORDER_TYPE = "limit", it fails (gets rejected).
        exchange.config.TP_ORDER_TYPE = "limit"

        res = await exchange.place_order(
            symbol="BTCUSDT",
            side="buy",
            order_type="limit",
            qty=1.0,
            price=100.0,
            tp_price=100.05,
            sl_price=95.0
        )

        assert res["code"] == "40001"
        assert "net tp profit below minimum required threshold" in res["msg"]

        await exchange.close()


def test_trade_reporter_standalone():
    from engine.reporting import TradeReporter

    reporter = TradeReporter(starting_equity=100.0)
    assert reporter.equity == 100.0
    assert reporter.cumulative_pnl == 0.0

    # Record entry symmetrically
    reporter.record_entry("BTCUSDT", "buy", 1.0, 50000.0, 10.0, "test_strat")

    # Record first partial exit
    reporter.record_exit(
        symbol="BTCUSDT",
        side="buy",
        round_trip_pnl=10.0,
        exit_type="tp",
        is_be=False,
        is_partial=True,
        margin=10.0,
        strategy_id="test_strat",
        use_virtual_balance_or_paper=True
    )

    # Since it is a partial exit, total_trades shouldn't increment, but equity should
    assert reporter.equity == 110.0
    assert reporter.total_trades == 0
    assert reporter.cumulative_pnl == 10.0

    # Record second final exit
    total_trade_pnl = reporter.record_exit(
        symbol="BTCUSDT",
        side="buy",
        round_trip_pnl=5.0,
        exit_type="tp",
        is_be=False,
        is_partial=False,
        margin=10.0,
        strategy_id="test_strat",
        use_virtual_balance_or_paper=True
    )

    # Settle trades
    assert total_trade_pnl == 15.0
    assert reporter.equity == 115.0
    assert reporter.total_trades == 1
    assert reporter.winning_trades == 1
    assert reporter.cumulative_pnl == 15.0
    assert reporter.strategy_stats["test_strat"]["pnl"] == 15.0
    assert reporter.asset_stats["BTCUSDT"]["pnl"] == 15.0


def test_config_validation_on_overrides():
    from pydantic import ValidationError
    from config import ConfigContext

    # Sane override should succeed
    ctx = ConfigContext(WEIGHT_RSI=1.5, RISK_PER_TRADE=0.05)
    assert ctx.WEIGHT_RSI == 1.5
    assert ctx.RISK_PER_TRADE == 0.05

    # Out-of-bounds override (WEIGHT_RSI max is 10.0) should raise ValidationError
    with pytest.raises(ValidationError):
        ConfigContext(WEIGHT_RSI=999.0)

    # Invalid type override (RISK_PER_TRADE float to str) should raise ValidationError
    with pytest.raises(ValidationError):
        ConfigContext(RISK_PER_TRADE="not a number")
