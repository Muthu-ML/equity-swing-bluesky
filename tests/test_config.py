import os
from bot.config import load_strategy_config, load_kite_config

def test_load_strategy_config_defaults(monkeypatch):
    for var in ["STARTING_CAPITAL", "RISK_PER_TRADE_PCT", "MAX_POSITIONS",
                "POSITION_CAP_PCT", "HARD_STOP_PCT", "RS_FLOOR",
                "PENDING_ORDER_EXPIRY_SESSIONS", "DAILY_LOSS_LIMIT_PCT",
                "GAP_THRESHOLD_PCT", "CANDIDATES_FILE_PATH"]:
        monkeypatch.delenv(var, raising=False)

    config = load_strategy_config()

    assert config.starting_capital == 1000000.0
    assert config.risk_per_trade_pct == 0.01
    assert config.max_positions == 8
    assert config.position_cap_pct == 0.30
    assert config.hard_stop_pct == 0.07
    assert config.rs_floor == 70
    assert config.pending_order_expiry_sessions == 5
    assert config.daily_loss_limit_pct == 0.03
    assert config.gap_threshold_pct == 0.02
    assert config.candidates_file_path == "candidates.csv"

def test_load_strategy_config_overrides(monkeypatch):
    monkeypatch.setenv("STARTING_CAPITAL", "500000")
    monkeypatch.setenv("RS_FLOOR", "85")
    monkeypatch.setenv("CANDIDATES_FILE_PATH", "data/candidates.csv")

    config = load_strategy_config()

    assert config.starting_capital == 500000.0
    assert config.rs_floor == 85
    assert config.candidates_file_path == "data/candidates.csv"

def test_load_kite_config_reads_env(monkeypatch):
    monkeypatch.setenv("KITE_API_KEY", "abc")
    monkeypatch.setenv("KITE_API_SECRET", "def")
    monkeypatch.setenv("KITE_ACCESS_TOKEN", "ghi")

    config = load_kite_config()

    assert config.api_key == "abc"
    assert config.api_secret == "def"
    assert config.access_token == "ghi"
