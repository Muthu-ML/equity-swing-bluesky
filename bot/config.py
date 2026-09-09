import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv, set_key

@dataclass
class StrategyConfig:
    starting_capital: float
    risk_per_trade_pct: float
    max_positions: int
    position_cap_pct: float
    hard_stop_pct: float
    rs_floor: int
    pending_order_expiry_sessions: int
    daily_loss_limit_pct: float
    gap_threshold_pct: float

@dataclass
class KiteConfig:
    api_key: str | None
    api_secret: str | None
    access_token: str | None

ENV_PATH = Path(".env")

def load_dotenv_if_present() -> None:
    if ENV_PATH.exists():
        load_dotenv(ENV_PATH)

def load_strategy_config() -> StrategyConfig:
    return StrategyConfig(
        starting_capital=float(os.getenv("STARTING_CAPITAL", "1000000")),
        risk_per_trade_pct=float(os.getenv("RISK_PER_TRADE_PCT", "0.01")),
        max_positions=int(os.getenv("MAX_POSITIONS", "8")),
        position_cap_pct=float(os.getenv("POSITION_CAP_PCT", "0.30")),
        hard_stop_pct=float(os.getenv("HARD_STOP_PCT", "0.07")),
        rs_floor=int(os.getenv("RS_FLOOR", "70")),
        pending_order_expiry_sessions=int(os.getenv("PENDING_ORDER_EXPIRY_SESSIONS", "5")),
        daily_loss_limit_pct=float(os.getenv("DAILY_LOSS_LIMIT_PCT", "0.03")),
        gap_threshold_pct=float(os.getenv("GAP_THRESHOLD_PCT", "0.02")),
    )

def load_kite_config() -> KiteConfig:
    return KiteConfig(
        api_key=os.getenv("KITE_API_KEY"),
        api_secret=os.getenv("KITE_API_SECRET"),
        access_token=os.getenv("KITE_ACCESS_TOKEN"),
    )

def save_access_token(token: str) -> None:
    if not ENV_PATH.exists():
        ENV_PATH.touch()
    set_key(str(ENV_PATH), "KITE_ACCESS_TOKEN", token)
