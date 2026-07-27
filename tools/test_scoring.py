"""
1. Summary: Validates that ScoringEngine score distributions align with weights and thresholds.
2. Description: Tests penalty offsets, directional multipliers, and entry decisions.
3. Context: Guarantees correct operation of the continuous scoring pipeline.
"""
import os
import shutil
import pytest
from config import ConfigContext
from ta.scoring import ScoringEngine
from engine.core import Engine

def test_scoring_engine_calculations():
    # 1. Setup mock features
    features = {
        "rsi": 75.0,           # RSI > 50 -> raw bullish bias (+50)
        "adx": 30.0,
        "imbalance": 0.8,      # highly bullish raw imbalance (+80)
        "macd_hist": 0.05,
        "atr": 0.1,
        "asset_15m": 0.0002,   # > 0.0001 -> bullish raw trend (+100)
        "supertrend_dir": 1,   # bullish (+100)
        "drt": 0.7,            # (0.7 - 0.5) * 200 = +40
        "btc_15m": 0.0015,     # > 0.001 -> +100
        "btc_1h": 0.0005,
        "btc_4h": 0.0002,
        "btc_1d": 0.0002,
        "bias": "bullish",     # +100
        "structure_signal": "bullish_bos", # +100
        "volume_influx": True,
        "volume_spike": True,  # perfect -> 0 penalty
        "mid": 1.0,
        "spread_pct": 0.001,   # <= 0.002 -> 0 penalty
        "vol_pct": 0.05,       # >= 0.01 -> 0 penalty
        "confidence": 0.8      # >= 0.66 -> 0 penalty
    }

    # Create a clean config context with specific weights
    cfg = ConfigContext(
        ENTRY_SCORE_THRESHOLD=30.0,
        BY_DEFAULT_REPORT_ONLY=False,
        CONTRARIAN_FILTER=False,
        WEIGHT_RSI=1.0,
        WEIGHT_IMBALANCE=1.5,
        WEIGHT_TREND_15M=1.0,
        WEIGHT_SUPERTREND=1.0,
        WEIGHT_DRT=1.0,
        WEIGHT_BTC_MOM=1.0,
        WEIGHT_HTF_BIAS=1.0,
        WEIGHT_STRUCTURE=1.0,
        WEIGHT_VOL_INFLUX=1.0,
        WEIGHT_ATR=1.0,
        WEIGHT_SPREAD=1.0,
        WEIGHT_VOL_PCT=1.0,
        WEIGHT_CONFIDENCE=1.0
    )

    se = ScoringEngine()

    # 2. Evaluate for BUY (Long)
    res_buy = se.evaluate(features, side="buy", config_context=cfg)
    assert res_buy["side"] == "buy"
    assert res_buy["raw_scores"]["rsi"] == pytest.approx(50.0)  # (75 - 50) * 2
    assert res_buy["raw_scores"]["imbalance"] == pytest.approx(80.0)
    assert res_buy["raw_scores"]["drt"] == pytest.approx(40.0)
    assert res_buy["raw_scores"]["vol_influx"] == pytest.approx(0.0)  # no penalty

    # Check aggregation bounds
    assert -100.0 <= res_buy["aggregated_score"] <= 100.0
    assert res_buy["decision"] == "TAKEN"  # Strong bullish confluence passes threshold 30.0

    # 3. Evaluate with CONTRARIAN_FILTER = True
    cfg_contrarian = ConfigContext(
        ENTRY_SCORE_THRESHOLD=30.0,
        BY_DEFAULT_REPORT_ONLY=False,
        CONTRARIAN_FILTER=True,
        WEIGHT_RSI=1.0,
        WEIGHT_IMBALANCE=1.5
    )
    res_contrarian = se.evaluate(features, side="buy", config_context=cfg_contrarian)
    # Scores should be inverted: RSI +50 becomes -50, Imbalance +80 becomes -80
    assert res_contrarian["raw_scores"]["rsi"] == -50.0
    assert res_contrarian["raw_scores"]["imbalance"] == -80.0


def test_metrics_log_schema_integration():
    # Instantiate simulation engine with mock
    engine = Engine(use_db=False, mode="paper")

    # Construct test scoring result
    scoring_result = {
        "aggregated_score": 45.1234,
        "entry_threshold": 30.0,
        "decision": "TAKEN",
        "reason": "Passed threshold",
        "raw_scores": {k: 50.0 for k in ["rsi", "rsi_ceiling", "imbalance", "macd", "trend_15m", "supertrend", "drt", "sanity", "btc_mom", "btc_conf", "htf_bias", "structure", "vol_influx", "atr", "spread", "vol_pct", "confidence"]},
        "weighted_scores": {k: 75.0 for k in ["rsi", "rsi_ceiling", "imbalance", "macd", "trend_15m", "supertrend", "drt", "sanity", "btc_mom", "btc_conf", "htf_bias", "structure", "vol_influx", "atr", "spread", "vol_pct", "confidence"]}
    }

    # Write metrics log
    engine._write_metrics_log("TESTBTCUSDT", "buy", "test_strategy", scoring_result)

    # Locate the created log file
    import glob
    log_files = glob.glob("docs/temp/*.metrics-log.txt")
    assert len(log_files) > 0

    latest_file = max(log_files, key=os.path.getctime)
    with open(latest_file, "r") as f:
        lines = f.readlines()

    # The log file should contain at least 2 lines (header + 1 record)
    assert len(lines) >= 2
    header = lines[0].strip().split(",")
    row = lines[1].strip().split(",")

    # Verify column count is exactly 42
    assert len(header) == 42
    assert len(row) == 42

    # Verify exact placement of key metrics
    assert header[0] == "timestamp"
    assert header[1] == "symbol"
    assert header[2] == "target_side"
    assert header[3] == "strategy_id"
    assert header[-4] == "aggregated_score"
    assert header[-3] == "entry_threshold"
    assert header[-2] == "decision"
    assert header[-1] == "rejection_reason"

    assert row[1] == "TESTBTCUSDT"
    assert row[2] == "buy"
    assert row[3] == "test_strategy"
    assert float(row[-4]) == 45.1234
    assert float(row[-3]) == 30.0
    assert row[-2] == "TAKEN"
