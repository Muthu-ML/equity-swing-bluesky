# Blue Sky Breakout Bot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a console-based, paper-trading-only implementation of the "Blue Sky" breakout strategy from `blue-sky-breakout-bot-spec.md`, with manual candidate entry, Zerodha Kite Connect market data, SQLite persistence, and a broker-execution layer ready for a future live-trading adapter.

**Architecture:** A Python package (`bot/`) of small, single-responsibility modules — pure logic (sizing, exit rules, risk checks) separate from I/O (SQLite storage, Kite market data, console input) — composed by a `workflow.py` orchestrator and driven by a console menu (`cli.py`/`main.py`). Only `market_data.py` and `broker_executor.py` talk to Kite; everything else is testable with fakes, no network access required for the test suite.

**Tech Stack:** Python 3.11+, `kiteconnect` (official Zerodha SDK), stdlib `sqlite3`, `python-dotenv`, `pytest`.

**Spec:** `docs/superpowers/specs/2026-09-10-blue-sky-breakout-bot-design.md` (design doc), which itself implements `blue-sky-breakout-bot-spec.md` (source strategy spec, repo root). Read both — this plan argues from them and does not repeat every rationale.

**Correction vs. the approved design doc:** the design doc's §4 workflow narrative described exits as filling the same day they're marked. The source spec is explicit (§4, last bullet): *"All exits execute at the next session's open once a daily close breaches the applicable stop."* This plan implements that correctly — exits are marked on the day of the close-breach and filled at the next run's open, exactly mirroring how pending entries already work. Same-day fill would be a bug relative to the source spec's stated mechanics.

## Global Constraints

(Exact values from `blue-sky-breakout-bot-spec.md`, parameterized as defaults — every task's config defaults must match these.)

- Risk per trade: 1% of current account equity (`risk_per_trade_pct = 0.01`)
- Max concurrent positions: 8 (`max_positions = 8`)
- Position size cap: 30% of account equity per position (`position_cap_pct = 0.30`)
- Initial hard stop: 7% below actual fill price (`hard_stop_pct = 0.07`)
- Trend exit: trail 50-day MA once a daily close has occurred above it since entry; never reverts to the fixed stop once activated
- RS floor when filtering candidates: default ≥70 (`rs_floor = 70`, configurable)
- Ranking when candidates > open slots: highest RS rating first
- Reference starting capital: ₹10,00,000, parameterized (`starting_capital = 1000000`)
- Market filter: none — trade in all conditions (not modeled as a filter anywhere)
- Exits execute at the next session's open once a daily close breaches the applicable stop (not same-day)
- Entries are buy-stop/GTT orders at the pivot for the next session; if that session's high clears the pivot, fill at the pivot (or at the open if it gapped above pivot)
- Live order placement is out of scope this phase — `KiteLiveExecutor` is a stub only
- No automated/scraped access to bananapatterns.com anywhere in this codebase
- Console only — no web UI

---

### Task 1: Project scaffolding & configuration

**Files:**
- Create: `requirements.txt`
- Create: `.env.example`
- Create: `bot/__init__.py`
- Create: `bot/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `StrategyConfig` dataclass (`starting_capital`, `risk_per_trade_pct`, `max_positions`, `position_cap_pct`, `hard_stop_pct`, `rs_floor`, `pending_order_expiry_sessions`, `daily_loss_limit_pct`, `gap_threshold_pct`), `KiteConfig` dataclass (`api_key`, `api_secret`, `access_token`), `load_strategy_config() -> StrategyConfig`, `load_kite_config() -> KiteConfig`, `load_dotenv_if_present() -> None`, `save_access_token(token: str) -> None`.

- [ ] **Step 1: Initialize the project**

```bash
mkdir -p bot tests
git init
```

Create `requirements.txt`:

```
kiteconnect>=5.0.1
python-dotenv>=1.0.1
pytest>=8.0.0
```

Create `.env.example`:

```
KITE_API_KEY=
KITE_API_SECRET=
KITE_ACCESS_TOKEN=
STARTING_CAPITAL=1000000
RISK_PER_TRADE_PCT=0.01
MAX_POSITIONS=8
POSITION_CAP_PCT=0.30
HARD_STOP_PCT=0.07
RS_FLOOR=70
PENDING_ORDER_EXPIRY_SESSIONS=5
DAILY_LOSS_LIMIT_PCT=0.03
GAP_THRESHOLD_PCT=0.02
```

Create empty `bot/__init__.py`.

Create a `.gitignore`:

```
.env
bot_state.db
__pycache__/
*.pyc
.pytest_cache/
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_config.py
import os
from bot.config import load_strategy_config, load_kite_config

def test_load_strategy_config_defaults(monkeypatch):
    for var in ["STARTING_CAPITAL", "RISK_PER_TRADE_PCT", "MAX_POSITIONS",
                "POSITION_CAP_PCT", "HARD_STOP_PCT", "RS_FLOOR",
                "PENDING_ORDER_EXPIRY_SESSIONS", "DAILY_LOSS_LIMIT_PCT",
                "GAP_THRESHOLD_PCT"]:
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

def test_load_strategy_config_overrides(monkeypatch):
    monkeypatch.setenv("STARTING_CAPITAL", "500000")
    monkeypatch.setenv("RS_FLOOR", "85")

    config = load_strategy_config()

    assert config.starting_capital == 500000.0
    assert config.rs_floor == 85

def test_load_kite_config_reads_env(monkeypatch):
    monkeypatch.setenv("KITE_API_KEY", "abc")
    monkeypatch.setenv("KITE_API_SECRET", "def")
    monkeypatch.setenv("KITE_ACCESS_TOKEN", "ghi")

    config = load_kite_config()

    assert config.api_key == "abc"
    assert config.api_secret == "def"
    assert config.access_token == "ghi"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bot.config'`

- [ ] **Step 4: Write minimal implementation**

```python
# bot/config.py
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
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Commit**

```bash
git add requirements.txt .env.example .gitignore bot/__init__.py bot/config.py tests/test_config.py
git commit -m "chore: project scaffolding and config loading"
```

---

### Task 2: Data models & SQLite storage

**Files:**
- Create: `bot/models.py`
- Create: `bot/storage.py`
- Test: `tests/test_storage.py`

**Interfaces:**
- Consumes: nothing (foundation layer)
- Produces: `Candidate`, `PendingOrder`, `Position`, `Trade` dataclasses (`bot.models`); `Storage` class (`bot.storage`) with methods: `add_position`, `get_open_positions`, `update_position_trailing`, `mark_position_exit_pending`, `remove_position`, `add_pending_order`, `get_pending_orders`, `increment_pending_order_wait`, `remove_pending_order`, `log_trade`, `get_trade_log`, `record_equity`, `get_latest_equity`, `get_equity_peak`, `get_kill_switch`, `set_kill_switch`, `get_cash_balance`, `set_cash_balance`, `close`.

- [ ] **Step 1: Write the models**

```python
# bot/models.py
from dataclasses import dataclass, field

@dataclass
class Candidate:
    symbol: str
    pivot_price: float
    rs_rating: int
    current_price: float
    ma_50: float

@dataclass
class PendingOrder:
    id: int | None
    symbol: str
    pivot_price: float
    rs_at_selection: int
    order_date: str
    quantity: int
    sessions_waited: int = 0

@dataclass
class Position:
    id: int | None
    symbol: str
    entry_date: str
    entry_price: float
    quantity: int
    rs_at_entry: int
    hard_stop: float
    trailing_active: bool
    pivot_price: float
    exit_pending: bool = False
    exit_reason: str | None = None
    exit_trigger_price: float | None = None

@dataclass
class Trade:
    id: int | None
    symbol: str
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    quantity: int
    rs_at_entry: int
    return_pct: float
    exit_reason: str
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_storage.py
import pytest
from bot.storage import Storage
from bot.models import Position, PendingOrder, Trade

@pytest.fixture
def storage(tmp_path):
    s = Storage(str(tmp_path / "test.db"))
    yield s
    s.close()

def test_add_and_get_open_positions(storage):
    pos = Position(id=None, symbol="INFY", entry_date="2026-01-05", entry_price=1500.0,
                    quantity=10, rs_at_entry=88, hard_stop=1395.0, trailing_active=False,
                    pivot_price=1490.0)
    pid = storage.add_position(pos)

    positions = storage.get_open_positions()

    assert len(positions) == 1
    assert positions[0].id == pid
    assert positions[0].symbol == "INFY"
    assert positions[0].trailing_active is False
    assert positions[0].exit_pending is False

def test_update_position_trailing_and_mark_exit_pending(storage):
    pos = Position(id=None, symbol="TCS", entry_date="2026-01-05", entry_price=3800.0,
                    quantity=5, rs_at_entry=90, hard_stop=3534.0, trailing_active=False,
                    pivot_price=3780.0)
    pid = storage.add_position(pos)

    storage.update_position_trailing(pid, True)
    storage.mark_position_exit_pending(pid, "trailing_ma", 3750.0)

    updated = storage.get_open_positions()[0]
    assert updated.trailing_active is True
    assert updated.exit_pending is True
    assert updated.exit_reason == "trailing_ma"
    assert updated.exit_trigger_price == 3750.0

def test_remove_position(storage):
    pos = Position(id=None, symbol="WIPRO", entry_date="2026-01-05", entry_price=500.0,
                    quantity=20, rs_at_entry=75, hard_stop=465.0, trailing_active=False,
                    pivot_price=495.0)
    pid = storage.add_position(pos)

    storage.remove_position(pid)

    assert storage.get_open_positions() == []

def test_pending_orders_roundtrip(storage):
    order = PendingOrder(id=None, symbol="HDFCBANK", pivot_price=1700.0, rs_at_selection=80,
                          order_date="2026-01-05", quantity=15)
    oid = storage.add_pending_order(order)

    orders = storage.get_pending_orders()
    assert len(orders) == 1
    assert orders[0].id == oid
    assert orders[0].sessions_waited == 0

    storage.increment_pending_order_wait(oid)
    orders = storage.get_pending_orders()
    assert orders[0].sessions_waited == 1

    storage.remove_pending_order(oid)
    assert storage.get_pending_orders() == []

def test_trade_log_roundtrip(storage):
    trade = Trade(id=None, symbol="ITC", entry_date="2026-01-05", exit_date="2026-01-10",
                   entry_price=400.0, exit_price=372.0, quantity=25, rs_at_entry=72,
                   return_pct=-7.0, exit_reason="hard_stop")
    storage.log_trade(trade)

    log = storage.get_trade_log()
    assert len(log) == 1
    assert log[0].symbol == "ITC"
    assert log[0].return_pct == -7.0

def test_equity_history_and_peak(storage):
    storage.record_equity("2026-01-05", 1000000.0, 1000000.0)
    storage.record_equity("2026-01-06", 1050000.0, 900000.0)

    assert storage.get_latest_equity() == (1050000.0, 900000.0)
    assert storage.get_equity_peak() == 1050000.0

def test_kill_switch_default_and_toggle(storage):
    assert storage.get_kill_switch() is False

    storage.set_kill_switch(True)
    assert storage.get_kill_switch() is True

    storage.set_kill_switch(False)
    assert storage.get_kill_switch() is False

def test_cash_balance_default_and_set(storage):
    assert storage.get_cash_balance(default=1000000.0) == 1000000.0

    storage.set_cash_balance(950000.0)
    assert storage.get_cash_balance() == 950000.0
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_storage.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bot.storage'`

- [ ] **Step 4: Write minimal implementation**

```python
# bot/storage.py
import sqlite3
from bot.models import Position, PendingOrder, Trade

SCHEMA = """
CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    entry_date TEXT NOT NULL,
    entry_price REAL NOT NULL,
    quantity INTEGER NOT NULL,
    rs_at_entry INTEGER NOT NULL,
    hard_stop REAL NOT NULL,
    trailing_active INTEGER NOT NULL DEFAULT 0,
    pivot_price REAL NOT NULL,
    exit_pending INTEGER NOT NULL DEFAULT 0,
    exit_reason TEXT,
    exit_trigger_price REAL
);
CREATE TABLE IF NOT EXISTS pending_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    pivot_price REAL NOT NULL,
    rs_at_selection INTEGER NOT NULL,
    order_date TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    sessions_waited INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS trade_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    entry_date TEXT NOT NULL,
    exit_date TEXT NOT NULL,
    entry_price REAL NOT NULL,
    exit_price REAL NOT NULL,
    quantity INTEGER NOT NULL,
    rs_at_entry INTEGER NOT NULL,
    return_pct REAL NOT NULL,
    exit_reason TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS equity_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    equity REAL NOT NULL,
    cash REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS kv_store (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

class Storage:
    def __init__(self, db_path: str):
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def add_position(self, position: Position) -> int:
        cur = self._conn.execute(
            "INSERT INTO positions (symbol, entry_date, entry_price, quantity, rs_at_entry, "
            "hard_stop, trailing_active, pivot_price, exit_pending, exit_reason, "
            "exit_trigger_price) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (position.symbol, position.entry_date, position.entry_price, position.quantity,
             position.rs_at_entry, position.hard_stop, int(position.trailing_active),
             position.pivot_price, int(position.exit_pending), position.exit_reason,
             position.exit_trigger_price),
        )
        self._conn.commit()
        return cur.lastrowid

    def get_open_positions(self) -> list[Position]:
        rows = self._conn.execute("SELECT * FROM positions").fetchall()
        return [
            Position(
                id=row["id"], symbol=row["symbol"], entry_date=row["entry_date"],
                entry_price=row["entry_price"], quantity=row["quantity"],
                rs_at_entry=row["rs_at_entry"], hard_stop=row["hard_stop"],
                trailing_active=bool(row["trailing_active"]), pivot_price=row["pivot_price"],
                exit_pending=bool(row["exit_pending"]), exit_reason=row["exit_reason"],
                exit_trigger_price=row["exit_trigger_price"],
            )
            for row in rows
        ]

    def update_position_trailing(self, position_id: int, trailing_active: bool) -> None:
        self._conn.execute(
            "UPDATE positions SET trailing_active = ? WHERE id = ?",
            (int(trailing_active), position_id),
        )
        self._conn.commit()

    def mark_position_exit_pending(self, position_id: int, reason: str,
                                    trigger_price: float) -> None:
        self._conn.execute(
            "UPDATE positions SET exit_pending = 1, exit_reason = ?, "
            "exit_trigger_price = ? WHERE id = ?",
            (reason, trigger_price, position_id),
        )
        self._conn.commit()

    def remove_position(self, position_id: int) -> None:
        self._conn.execute("DELETE FROM positions WHERE id = ?", (position_id,))
        self._conn.commit()

    def add_pending_order(self, order: PendingOrder) -> int:
        cur = self._conn.execute(
            "INSERT INTO pending_orders (symbol, pivot_price, rs_at_selection, order_date, "
            "quantity, sessions_waited) VALUES (?, ?, ?, ?, ?, ?)",
            (order.symbol, order.pivot_price, order.rs_at_selection, order.order_date,
             order.quantity, order.sessions_waited),
        )
        self._conn.commit()
        return cur.lastrowid

    def get_pending_orders(self) -> list[PendingOrder]:
        rows = self._conn.execute("SELECT * FROM pending_orders").fetchall()
        return [
            PendingOrder(
                id=row["id"], symbol=row["symbol"], pivot_price=row["pivot_price"],
                rs_at_selection=row["rs_at_selection"], order_date=row["order_date"],
                quantity=row["quantity"], sessions_waited=row["sessions_waited"],
            )
            for row in rows
        ]

    def increment_pending_order_wait(self, order_id: int) -> None:
        self._conn.execute(
            "UPDATE pending_orders SET sessions_waited = sessions_waited + 1 WHERE id = ?",
            (order_id,),
        )
        self._conn.commit()

    def remove_pending_order(self, order_id: int) -> None:
        self._conn.execute("DELETE FROM pending_orders WHERE id = ?", (order_id,))
        self._conn.commit()

    def log_trade(self, trade: Trade) -> int:
        cur = self._conn.execute(
            "INSERT INTO trade_log (symbol, entry_date, exit_date, entry_price, exit_price, "
            "quantity, rs_at_entry, return_pct, exit_reason) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (trade.symbol, trade.entry_date, trade.exit_date, trade.entry_price,
             trade.exit_price, trade.quantity, trade.rs_at_entry, trade.return_pct,
             trade.exit_reason),
        )
        self._conn.commit()
        return cur.lastrowid

    def get_trade_log(self) -> list[Trade]:
        rows = self._conn.execute("SELECT * FROM trade_log ORDER BY exit_date").fetchall()
        return [
            Trade(
                id=row["id"], symbol=row["symbol"], entry_date=row["entry_date"],
                exit_date=row["exit_date"], entry_price=row["entry_price"],
                exit_price=row["exit_price"], quantity=row["quantity"],
                rs_at_entry=row["rs_at_entry"], return_pct=row["return_pct"],
                exit_reason=row["exit_reason"],
            )
            for row in rows
        ]

    def record_equity(self, date: str, equity: float, cash: float) -> None:
        self._conn.execute(
            "INSERT INTO equity_history (date, equity, cash) VALUES (?, ?, ?)",
            (date, equity, cash),
        )
        self._conn.commit()

    def get_latest_equity(self) -> tuple[float, float] | None:
        row = self._conn.execute(
            "SELECT equity, cash FROM equity_history ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return (row["equity"], row["cash"]) if row else None

    def get_equity_peak(self) -> float:
        row = self._conn.execute("SELECT MAX(equity) AS peak FROM equity_history").fetchone()
        return row["peak"] if row and row["peak"] is not None else 0.0

    def _kv_get(self, key: str) -> str | None:
        row = self._conn.execute("SELECT value FROM kv_store WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def _kv_set(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO kv_store (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self._conn.commit()

    def get_kill_switch(self) -> bool:
        return self._kv_get("kill_switch") == "1"

    def set_kill_switch(self, value: bool) -> None:
        self._kv_set("kill_switch", "1" if value else "0")

    def get_cash_balance(self, default: float = 0.0) -> float:
        value = self._kv_get("cash_balance")
        return float(value) if value is not None else default

    def set_cash_balance(self, value: float) -> None:
        self._kv_set("cash_balance", str(value))
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_storage.py -v`
Expected: PASS (8 tests)

- [ ] **Step 6: Commit**

```bash
git add bot/models.py bot/storage.py tests/test_storage.py
git commit -m "feat: add data models and SQLite storage layer"
```

---

### Task 3: Position sizing

**Files:**
- Create: `bot/sizing.py`
- Test: `tests/test_sizing.py`

**Interfaces:**
- Consumes: nothing
- Produces: `compute_position_size(equity: float, pivot_price: float, risk_pct: float = 0.01, stop_pct: float = 0.07, position_cap_pct: float = 0.30) -> int`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_sizing.py
import pytest
from bot.sizing import compute_position_size

def test_normal_sizing_not_capped():
    # risk_amount = 1000000 * 0.01 = 10000; position_value = 10000/0.07 = 142857.14
    # cap = 1000000 * 0.30 = 300000, not hit; quantity = floor(142857.14 / 1490)
    quantity = compute_position_size(equity=1000000.0, pivot_price=1490.0)
    assert quantity == 95

def test_position_cap_triggers():
    # risk_amount = 5000000*0.01=50000; position_value=50000/0.07=714285.7
    # cap = 5000000*0.30=1500000, still under cap -> no cap triggered here.
    # Use a low pivot with huge equity so uncapped value exceeds the cap.
    quantity = compute_position_size(equity=50000000.0, pivot_price=100.0)
    capped_value = 50000000.0 * 0.30
    assert quantity == int(capped_value // 100.0)

def test_quantity_floors_down():
    quantity = compute_position_size(equity=100000.0, pivot_price=333.0)
    risk_amount = 100000.0 * 0.01
    position_value = min(risk_amount / 0.07, 100000.0 * 0.30)
    assert quantity == int(position_value // 333.0)

def test_zero_pivot_price_raises():
    with pytest.raises(ValueError):
        compute_position_size(equity=1000000.0, pivot_price=0.0)

def test_custom_risk_and_cap_params():
    quantity = compute_position_size(
        equity=1000000.0, pivot_price=500.0,
        risk_pct=0.02, stop_pct=0.05, position_cap_pct=0.20,
    )
    risk_amount = 1000000.0 * 0.02
    position_value = min(risk_amount / 0.05, 1000000.0 * 0.20)
    assert quantity == int(position_value // 500.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_sizing.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bot.sizing'`

- [ ] **Step 3: Write minimal implementation**

```python
# bot/sizing.py

def compute_position_size(
    equity: float,
    pivot_price: float,
    risk_pct: float = 0.01,
    stop_pct: float = 0.07,
    position_cap_pct: float = 0.30,
) -> int:
    if pivot_price <= 0:
        raise ValueError("pivot_price must be positive")

    risk_amount = equity * risk_pct
    position_value = risk_amount / stop_pct
    position_value = min(position_value, equity * position_cap_pct)
    return int(position_value // pivot_price)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_sizing.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add bot/sizing.py tests/test_sizing.py
git commit -m "feat: add position sizing formula"
```

---

### Task 4: Exit rules

**Files:**
- Create: `bot/exit_rules.py`
- Test: `tests/test_exit_rules.py`

**Interfaces:**
- Consumes: `Position` (`bot.models`)
- Produces: `ExitDecision` dataclass (`should_exit: bool`, `trailing_active: bool`, `stop_level: float`, `reason: str | None`), `evaluate_exit(position: Position, today_close: float, today_50dma: float) -> ExitDecision`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_exit_rules.py
from bot.models import Position
from bot.exit_rules import evaluate_exit

def make_position(hard_stop=930.0, trailing_active=False):
    return Position(
        id=1, symbol="TEST", entry_date="2026-01-01", entry_price=1000.0,
        quantity=10, rs_at_entry=80, hard_stop=hard_stop,
        trailing_active=trailing_active, pivot_price=995.0,
    )

def test_not_activated_close_above_hard_stop_no_exit():
    # MA (980) is kept ABOVE today's close (950) so trailing does NOT activate —
    # this test is specifically for the pre-activation fixed-hard-stop branch.
    position = make_position()
    decision = evaluate_exit(position, today_close=950.0, today_50dma=980.0)
    assert decision.should_exit is False
    assert decision.trailing_active is False
    assert decision.reason is None

def test_not_activated_close_below_hard_stop_exits():
    # MA (950) is kept ABOVE today's close (920) so trailing does NOT activate —
    # the exit here must come from the fixed hard stop, not the MA trail.
    position = make_position()
    decision = evaluate_exit(position, today_close=920.0, today_50dma=950.0)
    assert decision.should_exit is True
    assert decision.reason == "hard_stop"
    assert decision.stop_level == 930.0

def test_close_exactly_at_hard_stop_does_not_exit():
    position = make_position()
    decision = evaluate_exit(position, today_close=930.0, today_50dma=900.0)
    assert decision.should_exit is False

def test_first_close_above_ma_activates_trailing_same_day_no_exit():
    position = make_position()
    decision = evaluate_exit(position, today_close=1050.0, today_50dma=1000.0)
    assert decision.trailing_active is True
    assert decision.should_exit is False

def test_trailing_active_close_below_ma_exits():
    position = make_position(trailing_active=True)
    decision = evaluate_exit(position, today_close=990.0, today_50dma=1000.0)
    assert decision.should_exit is True
    assert decision.reason == "trailing_ma"
    assert decision.stop_level == 1000.0

def test_close_exactly_at_ma_does_not_exit():
    position = make_position(trailing_active=True)
    decision = evaluate_exit(position, today_close=1000.0, today_50dma=1000.0)
    assert decision.should_exit is False

def test_trailing_active_persists_even_if_dips_and_recovers():
    position = make_position(trailing_active=True)
    decision = evaluate_exit(position, today_close=1010.0, today_50dma=1000.0)
    assert decision.trailing_active is True
    assert decision.should_exit is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_exit_rules.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bot.exit_rules'`

- [ ] **Step 3: Write minimal implementation**

```python
# bot/exit_rules.py
from dataclasses import dataclass
from bot.models import Position

@dataclass
class ExitDecision:
    should_exit: bool
    trailing_active: bool
    stop_level: float
    reason: str | None

def evaluate_exit(position: Position, today_close: float, today_50dma: float) -> ExitDecision:
    trailing_active = position.trailing_active or (today_close > today_50dma)

    if trailing_active:
        should_exit = today_close < today_50dma
        stop_level = today_50dma
        reason = "trailing_ma" if should_exit else None
    else:
        should_exit = today_close < position.hard_stop
        stop_level = position.hard_stop
        reason = "hard_stop" if should_exit else None

    return ExitDecision(should_exit, trailing_active, stop_level, reason)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_exit_rules.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add bot/exit_rules.py tests/test_exit_rules.py
git commit -m "feat: add exit rule evaluation (hard stop + 50-day MA trailing)"
```

---

### Task 5: Risk control helpers

**Files:**
- Create: `bot/risk_controls.py`
- Test: `tests/test_risk_controls.py`

**Interfaces:**
- Consumes: `Position` (`bot.models`)
- Produces: `check_daily_loss_limit(equity_start_of_day: float, equity_now: float, limit_pct: float) -> bool`, `detect_gap(trigger_price: float, fill_price: float, gap_threshold_pct: float = 0.02) -> bool`, `reconcile_positions(positions: list[Position]) -> list[str]`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_risk_controls.py
from bot.models import Position
from bot.risk_controls import check_daily_loss_limit, detect_gap, reconcile_positions

def test_daily_loss_limit_not_breached():
    assert check_daily_loss_limit(1000000.0, 980000.0, 0.03) is False

def test_daily_loss_limit_breached():
    assert check_daily_loss_limit(1000000.0, 950000.0, 0.03) is True

def test_daily_loss_limit_exactly_at_threshold():
    assert check_daily_loss_limit(1000000.0, 970000.0, 0.03) is True

def test_detect_gap_below_threshold():
    assert detect_gap(trigger_price=1000.0, fill_price=1010.0, gap_threshold_pct=0.02) is False

def test_detect_gap_at_threshold():
    assert detect_gap(trigger_price=1000.0, fill_price=1020.0, gap_threshold_pct=0.02) is True

def test_detect_gap_above_threshold():
    assert detect_gap(trigger_price=1000.0, fill_price=1100.0, gap_threshold_pct=0.02) is True

def make_position(quantity=10, entry_price=100.0):
    return Position(id=1, symbol="X", entry_date="2026-01-01", entry_price=entry_price,
                     quantity=quantity, rs_at_entry=80, hard_stop=93.0,
                     trailing_active=False, pivot_price=99.0)

def test_reconcile_positions_clean():
    assert reconcile_positions([make_position()]) == []

def test_reconcile_positions_flags_bad_quantity():
    problems = reconcile_positions([make_position(quantity=0)])
    assert len(problems) == 1
    assert "X" in problems[0]

def test_reconcile_positions_flags_bad_entry_price():
    problems = reconcile_positions([make_position(entry_price=0.0)])
    assert len(problems) == 1

def test_reconcile_positions_empty_list():
    assert reconcile_positions([]) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_risk_controls.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bot.risk_controls'`

- [ ] **Step 3: Write minimal implementation**

```python
# bot/risk_controls.py
from bot.models import Position

def check_daily_loss_limit(equity_start_of_day: float, equity_now: float, limit_pct: float) -> bool:
    loss_pct = (equity_start_of_day - equity_now) / equity_start_of_day
    return loss_pct >= limit_pct

def detect_gap(trigger_price: float, fill_price: float, gap_threshold_pct: float = 0.02) -> bool:
    return abs(fill_price - trigger_price) / trigger_price >= gap_threshold_pct

def reconcile_positions(positions: list[Position]) -> list[str]:
    problems = []
    for position in positions:
        if position.quantity <= 0:
            problems.append(f"{position.symbol}: non-positive quantity ({position.quantity})")
        elif position.entry_price <= 0:
            problems.append(f"{position.symbol}: non-positive entry price ({position.entry_price})")
    return problems
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_risk_controls.py -v`
Expected: PASS (10 tests)

- [ ] **Step 5: Commit**

```bash
git add bot/risk_controls.py tests/test_risk_controls.py
git commit -m "feat: add daily loss limit, gap detection, and reconciliation checks"
```

---

### Task 6: Candidate input (manual console entry)

**Files:**
- Create: `bot/candidate_input.py`
- Test: `tests/test_candidate_input.py`

**Interfaces:**
- Consumes: `Candidate` (`bot.models`)
- Produces: `parse_candidate(raw: dict) -> Candidate`, `prompt_for_candidates(input_fn=input, print_fn=print) -> list[Candidate]`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_candidate_input.py
import pytest
from bot.candidate_input import parse_candidate, prompt_for_candidates

def test_parse_candidate_valid():
    candidate = parse_candidate({
        "symbol": "infy", "pivot_price": 1490.0, "rs_rating": 88,
        "current_price": 1495.0, "ma_50": 1400.0,
    })
    assert candidate.symbol == "INFY"
    assert candidate.pivot_price == 1490.0
    assert candidate.rs_rating == 88

def test_parse_candidate_rejects_zero_pivot():
    with pytest.raises(ValueError):
        parse_candidate({"symbol": "X", "pivot_price": 0.0, "rs_rating": 80,
                          "current_price": 100.0, "ma_50": 90.0})

def test_parse_candidate_rejects_out_of_range_rs():
    with pytest.raises(ValueError):
        parse_candidate({"symbol": "X", "pivot_price": 100.0, "rs_rating": 150,
                          "current_price": 100.0, "ma_50": 90.0})
    with pytest.raises(ValueError):
        parse_candidate({"symbol": "X", "pivot_price": 100.0, "rs_rating": 0,
                          "current_price": 100.0, "ma_50": 90.0})

def test_parse_candidate_rejects_zero_current_price_or_ma():
    with pytest.raises(ValueError):
        parse_candidate({"symbol": "X", "pivot_price": 100.0, "rs_rating": 80,
                          "current_price": 0.0, "ma_50": 90.0})
    with pytest.raises(ValueError):
        parse_candidate({"symbol": "X", "pivot_price": 100.0, "rs_rating": 80,
                          "current_price": 100.0, "ma_50": 0.0})

def test_prompt_for_candidates_stops_on_done():
    inputs = iter(["done"])
    prints = []
    candidates = prompt_for_candidates(
        input_fn=lambda _: next(inputs), print_fn=prints.append
    )
    assert candidates == []

def test_prompt_for_candidates_collects_one_entry():
    inputs = iter(["INFY", "1490", "88", "1495", "1400", "done"])
    prints = []
    candidates = prompt_for_candidates(
        input_fn=lambda _: next(inputs), print_fn=prints.append
    )
    assert len(candidates) == 1
    assert candidates[0].symbol == "INFY"
    assert candidates[0].rs_rating == 88

def test_prompt_for_candidates_skips_invalid_entry():
    inputs = iter(["BADRS", "100", "150", "100", "90", "done"])
    prints = []
    candidates = prompt_for_candidates(
        input_fn=lambda _: next(inputs), print_fn=prints.append
    )
    assert candidates == []
    assert any("Invalid" in message for message in prints)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_candidate_input.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bot.candidate_input'`

- [ ] **Step 3: Write minimal implementation**

```python
# bot/candidate_input.py
from bot.models import Candidate

def parse_candidate(raw: dict) -> Candidate:
    symbol = str(raw["symbol"]).strip().upper()
    pivot_price = float(raw["pivot_price"])
    rs_rating = int(raw["rs_rating"])
    current_price = float(raw["current_price"])
    ma_50 = float(raw["ma_50"])

    if pivot_price <= 0:
        raise ValueError("pivot_price must be positive")
    if not (1 <= rs_rating <= 99):
        raise ValueError("rs_rating must be between 1 and 99")
    if current_price <= 0:
        raise ValueError("current_price must be positive")
    if ma_50 <= 0:
        raise ValueError("ma_50 must be positive")

    return Candidate(symbol=symbol, pivot_price=pivot_price, rs_rating=rs_rating,
                      current_price=current_price, ma_50=ma_50)

def prompt_for_candidates(input_fn=input, print_fn=print) -> list[Candidate]:
    print_fn("Enter today's Fresh Breakout candidates. Type 'done' as the symbol to finish.")
    candidates = []
    while True:
        symbol = input_fn("Symbol (or 'done'): ").strip()
        if symbol.upper() == "DONE":
            break
        try:
            pivot_price = input_fn("Pivot price: ")
            rs_rating = input_fn("RS rating (1-99): ")
            current_price = input_fn("Current price: ")
            ma_50 = input_fn("50-day MA: ")
            candidate = parse_candidate({
                "symbol": symbol, "pivot_price": pivot_price, "rs_rating": rs_rating,
                "current_price": current_price, "ma_50": ma_50,
            })
            candidates.append(candidate)
        except (ValueError, KeyError) as error:
            print_fn(f"Invalid input for {symbol}, skipped: {error}")
    return candidates
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_candidate_input.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add bot/candidate_input.py tests/test_candidate_input.py
git commit -m "feat: add manual console candidate entry with validation"
```

---

### Task 7: Kite market data wrapper

**Files:**
- Create: `bot/market_data.py`
- Test: `tests/test_market_data.py`

**Interfaces:**
- Consumes: nothing (takes an injected Kite-like client)
- Produces: `DataUnavailableError` exception, `DailyBar` dataclass (`open`, `high`, `low`, `close`, `ma_50`), `KiteMarketData` class with `resolve_instrument_token(symbol: str) -> int` and `get_daily_bar(symbol: str, as_of_date) -> DailyBar`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_market_data.py
import pytest
from datetime import date
from bot.market_data import KiteMarketData, DataUnavailableError

class FakeKiteClient:
    def __init__(self, instruments=None, candles=None, raise_on_historical=False,
                 raise_on_instruments=False):
        self._instruments = instruments or []
        self._candles = candles or []
        self._raise_on_historical = raise_on_historical
        self._raise_on_instruments = raise_on_instruments

    def instruments(self, exchange):
        if self._raise_on_instruments:
            raise RuntimeError("network error")
        return self._instruments

    def historical_data(self, instrument_token, from_date, to_date, interval):
        if self._raise_on_historical:
            raise RuntimeError("rate limited")
        return self._candles

def make_candles(n, base_close=100.0):
    return [{"open": base_close + i, "high": base_close + i + 1,
             "low": base_close + i - 1, "close": base_close + i}
            for i in range(n)]

def test_resolve_instrument_token_found():
    client = FakeKiteClient(instruments=[{"tradingsymbol": "INFY", "instrument_token": 12345}])
    market_data = KiteMarketData(client)
    assert market_data.resolve_instrument_token("INFY") == 12345

def test_resolve_instrument_token_not_found_raises():
    client = FakeKiteClient(instruments=[{"tradingsymbol": "TCS", "instrument_token": 1}])
    market_data = KiteMarketData(client)
    with pytest.raises(DataUnavailableError):
        market_data.resolve_instrument_token("INFY")

def test_resolve_instrument_token_client_error_raises_data_unavailable():
    client = FakeKiteClient(raise_on_instruments=True)
    market_data = KiteMarketData(client)
    with pytest.raises(DataUnavailableError):
        market_data.resolve_instrument_token("INFY")

def test_get_daily_bar_computes_ma_and_returns_today_bar():
    candles = make_candles(50, base_close=100.0)
    client = FakeKiteClient(
        instruments=[{"tradingsymbol": "INFY", "instrument_token": 1}],
        candles=candles,
    )
    market_data = KiteMarketData(client)

    bar = market_data.get_daily_bar("INFY", date(2026, 1, 5))

    expected_ma = sum(c["close"] for c in candles) / 50
    assert bar.close == candles[-1]["close"]
    assert bar.open == candles[-1]["open"]
    assert bar.high == candles[-1]["high"]
    assert bar.low == candles[-1]["low"]
    assert bar.ma_50 == expected_ma

def test_get_daily_bar_insufficient_history_raises():
    candles = make_candles(10)
    client = FakeKiteClient(
        instruments=[{"tradingsymbol": "INFY", "instrument_token": 1}],
        candles=candles,
    )
    market_data = KiteMarketData(client)

    with pytest.raises(DataUnavailableError):
        market_data.get_daily_bar("INFY", date(2026, 1, 5))

def test_get_daily_bar_historical_fetch_error_raises_data_unavailable():
    client = FakeKiteClient(
        instruments=[{"tradingsymbol": "INFY", "instrument_token": 1}],
        raise_on_historical=True,
    )
    market_data = KiteMarketData(client)

    with pytest.raises(DataUnavailableError):
        market_data.get_daily_bar("INFY", date(2026, 1, 5))

def test_resolve_instrument_token_cached_after_first_lookup():
    client = FakeKiteClient(instruments=[{"tradingsymbol": "INFY", "instrument_token": 1}])
    market_data = KiteMarketData(client)
    market_data.resolve_instrument_token("INFY")
    client._instruments = []  # simulate the API becoming unavailable
    assert market_data.resolve_instrument_token("INFY") == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_market_data.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bot.market_data'`

- [ ] **Step 3: Write minimal implementation**

```python
# bot/market_data.py
from dataclasses import dataclass
from datetime import date, timedelta

class DataUnavailableError(Exception):
    pass

@dataclass
class DailyBar:
    open: float
    high: float
    low: float
    close: float
    ma_50: float

class KiteMarketData:
    def __init__(self, kite_client):
        self._kite = kite_client
        self._token_cache: dict[str, int] = {}

    def resolve_instrument_token(self, symbol: str) -> int:
        if symbol in self._token_cache:
            return self._token_cache[symbol]
        try:
            instruments = self._kite.instruments("NSE")
            for row in instruments:
                self._token_cache[row["tradingsymbol"]] = row["instrument_token"]
        except Exception as error:
            raise DataUnavailableError(f"{symbol}: instrument lookup failed: {error}") from error

        if symbol not in self._token_cache:
            raise DataUnavailableError(f"{symbol}: not found in NSE instrument list")
        return self._token_cache[symbol]

    def get_daily_bar(self, symbol: str, as_of_date) -> DailyBar:
        instrument_token = self.resolve_instrument_token(symbol)
        try:
            if isinstance(as_of_date, str):
                as_of_date = date.fromisoformat(as_of_date)
            from_date = as_of_date - timedelta(days=90)
            candles = self._kite.historical_data(instrument_token, from_date, as_of_date, "day")
            if len(candles) < 50:
                raise DataUnavailableError(
                    f"{symbol}: insufficient history ({len(candles)} candles, need 50)"
                )
            last_50 = candles[-50:]
            ma_50 = sum(c["close"] for c in last_50) / 50
            today = candles[-1]
            return DailyBar(open=today["open"], high=today["high"], low=today["low"],
                             close=today["close"], ma_50=ma_50)
        except DataUnavailableError:
            raise
        except Exception as error:
            raise DataUnavailableError(f"{symbol}: historical data fetch failed: {error}") from error
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_market_data.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add bot/market_data.py tests/test_market_data.py
git commit -m "feat: add Kite Connect market data wrapper (instrument lookup, OHLC, 50-day MA)"
```

---

### Task 8: Broker executor (paper + live stub)

**Files:**
- Create: `bot/broker_executor.py`
- Test: `tests/test_broker_executor.py`

**Interfaces:**
- Consumes: `Storage` (`bot.storage`), `Position`, `Trade` (`bot.models`)
- Produces: `BrokerExecutor` abstract base class (`submit_entry`, `submit_exit`), `PaperExecutor(storage: Storage)`, `KiteLiveExecutor()`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_broker_executor.py
import pytest
from bot.storage import Storage
from bot.broker_executor import PaperExecutor, KiteLiveExecutor

@pytest.fixture
def storage(tmp_path):
    s = Storage(str(tmp_path / "test.db"))
    s.set_cash_balance(1000000.0)
    yield s
    s.close()

def test_submit_entry_creates_position_and_debits_cash(storage):
    executor = PaperExecutor(storage)

    position = executor.submit_entry(
        symbol="INFY", quantity=10, fill_price=1500.0, rs_rating=88,
        pivot_price=1490.0, entry_date="2026-01-05",
    )

    assert position.id is not None
    assert position.hard_stop == pytest.approx(1500.0 * 0.93)
    assert storage.get_cash_balance() == 1000000.0 - 15000.0
    assert len(storage.get_open_positions()) == 1

def test_submit_exit_removes_position_credits_cash_and_logs_trade(storage):
    executor = PaperExecutor(storage)
    position = executor.submit_entry(
        symbol="INFY", quantity=10, fill_price=1500.0, rs_rating=88,
        pivot_price=1490.0, entry_date="2026-01-05",
    )
    cash_after_entry = storage.get_cash_balance()

    trade = executor.submit_exit(position, exit_price=1400.0, exit_date="2026-01-10",
                                  reason="hard_stop")

    assert trade.return_pct == pytest.approx((1400.0 - 1500.0) / 1500.0 * 100)
    assert storage.get_cash_balance() == cash_after_entry + 10 * 1400.0
    assert storage.get_open_positions() == []
    assert len(storage.get_trade_log()) == 1

def test_kite_live_executor_not_implemented():
    executor = KiteLiveExecutor()
    with pytest.raises(NotImplementedError):
        executor.submit_entry(symbol="INFY", quantity=10, fill_price=1500.0, rs_rating=88,
                               pivot_price=1490.0, entry_date="2026-01-05")
    with pytest.raises(NotImplementedError):
        executor.submit_exit(None, exit_price=1400.0, exit_date="2026-01-10", reason="hard_stop")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_broker_executor.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bot.broker_executor'`

- [ ] **Step 3: Write minimal implementation**

```python
# bot/broker_executor.py
from abc import ABC, abstractmethod
from bot.models import Position, Trade
from bot.storage import Storage

class BrokerExecutor(ABC):
    @abstractmethod
    def submit_entry(self, symbol: str, quantity: int, fill_price: float, rs_rating: int,
                      pivot_price: float, entry_date: str) -> Position:
        ...

    @abstractmethod
    def submit_exit(self, position: Position, exit_price: float, exit_date: str,
                     reason: str) -> Trade:
        ...

class PaperExecutor(BrokerExecutor):
    def __init__(self, storage: Storage):
        self._storage = storage

    def submit_entry(self, symbol: str, quantity: int, fill_price: float, rs_rating: int,
                      pivot_price: float, entry_date: str) -> Position:
        cost = quantity * fill_price
        self._storage.set_cash_balance(self._storage.get_cash_balance() - cost)

        position = Position(
            id=None, symbol=symbol, entry_date=entry_date, entry_price=fill_price,
            quantity=quantity, rs_at_entry=rs_rating, hard_stop=fill_price * 0.93,
            trailing_active=False, pivot_price=pivot_price,
        )
        position.id = self._storage.add_position(position)
        return position

    def submit_exit(self, position: Position, exit_price: float, exit_date: str,
                     reason: str) -> Trade:
        proceeds = position.quantity * exit_price
        self._storage.set_cash_balance(self._storage.get_cash_balance() + proceeds)

        return_pct = (exit_price - position.entry_price) / position.entry_price * 100
        trade = Trade(
            id=None, symbol=position.symbol, entry_date=position.entry_date,
            exit_date=exit_date, entry_price=position.entry_price, exit_price=exit_price,
            quantity=position.quantity, rs_at_entry=position.rs_at_entry,
            return_pct=return_pct, exit_reason=reason,
        )
        self._storage.log_trade(trade)
        self._storage.remove_position(position.id)
        return trade

class KiteLiveExecutor(BrokerExecutor):
    def submit_entry(self, symbol: str, quantity: int, fill_price: float, rs_rating: int,
                      pivot_price: float, entry_date: str) -> Position:
        raise NotImplementedError("Live trading is not implemented in this phase")

    def submit_exit(self, position: Position, exit_price: float, exit_date: str,
                     reason: str) -> Trade:
        raise NotImplementedError("Live trading is not implemented in this phase")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_broker_executor.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add bot/broker_executor.py tests/test_broker_executor.py
git commit -m "feat: add paper broker executor and live-executor stub"
```

---

### Task 9: Workflow — exit processing

**Files:**
- Create: `bot/workflow.py`
- Test: `tests/test_workflow_exits.py`

**Interfaces:**
- Consumes: `Storage`, `KiteMarketData`/`DataUnavailableError`, `BrokerExecutor`, `evaluate_exit` (`bot.exit_rules`), `detect_gap` (`bot.risk_controls`), `StrategyConfig`
- Produces: `process_exits(storage, market_data, executor, today: str, config) -> dict` returning `{"executed_exits": [...], "newly_marked": [...], "gap_fills": [...], "data_errors": [...], "halted": bool}`. A gap fill is an executed exit whose actual fill (today's open) is materially worse than the trigger price marked the previous day (§6 gap protection) — flagged, not silently absorbed.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_workflow_exits.py
import pytest
from bot.storage import Storage
from bot.models import Position, Trade
from bot.market_data import DataUnavailableError
from bot.config import StrategyConfig
from bot.workflow import process_exits

def make_config(**overrides):
    defaults = dict(starting_capital=1000000.0, risk_per_trade_pct=0.01, max_positions=8,
                     position_cap_pct=0.30, hard_stop_pct=0.07, rs_floor=70,
                     pending_order_expiry_sessions=5, daily_loss_limit_pct=0.03,
                     gap_threshold_pct=0.02)
    defaults.update(overrides)
    return StrategyConfig(**defaults)

class FakeMarketData:
    def __init__(self, bars=None, errors=None):
        self._bars = bars or {}
        self._errors = errors or set()

    def get_daily_bar(self, symbol, as_of_date):
        if symbol in self._errors:
            raise DataUnavailableError(f"{symbol}: no data")
        return self._bars[symbol]

class Bar:
    def __init__(self, open, high, low, close, ma_50):
        self.open, self.high, self.low, self.close, self.ma_50 = open, high, low, close, ma_50

class FakeExecutor:
    def __init__(self):
        self.exit_calls = []

    def submit_exit(self, position, exit_price, exit_date, reason):
        self.exit_calls.append((position.symbol, exit_price, reason))
        return_pct = (exit_price - position.entry_price) / position.entry_price * 100
        return Trade(id=1, symbol=position.symbol, entry_date=position.entry_date,
                     exit_date=exit_date, entry_price=position.entry_price,
                     exit_price=exit_price, quantity=position.quantity,
                     rs_at_entry=position.rs_at_entry, return_pct=return_pct, exit_reason=reason)

@pytest.fixture
def storage(tmp_path):
    s = Storage(str(tmp_path / "test.db"))
    yield s
    s.close()

def test_kill_switch_halts_processing(storage):
    storage.set_kill_switch(True)
    result = process_exits(storage, FakeMarketData(), FakeExecutor(), "2026-01-06", make_config())
    assert result["halted"] is True
    assert result["executed_exits"] == []

def test_executes_previously_marked_exit_at_todays_open(storage):
    position = Position(id=None, symbol="INFY", entry_date="2026-01-01", entry_price=1500.0,
                         quantity=10, rs_at_entry=88, hard_stop=1395.0, trailing_active=False,
                         pivot_price=1490.0, exit_pending=True, exit_reason="hard_stop",
                         exit_trigger_price=1395.0)
    storage.add_position(position)
    market_data = FakeMarketData(bars={"INFY": Bar(1380.0, 1390.0, 1370.0, 1385.0, 1420.0)})
    executor = FakeExecutor()

    result = process_exits(storage, market_data, executor, "2026-01-06", make_config())

    assert executor.exit_calls == [("INFY", 1380.0, "hard_stop")]
    assert result["executed_exits"][0]["exit_price"] == 1380.0
    assert storage.get_open_positions() == []

def test_exit_fill_materially_worse_than_trigger_flagged_as_gap(storage):
    # trigger (hard stop) was 1395.0; today's open gaps down to 1300.0 — a ~6.8% gap,
    # well past the default 2% gap_threshold_pct.
    position = Position(id=None, symbol="INFY", entry_date="2026-01-01", entry_price=1500.0,
                         quantity=10, rs_at_entry=88, hard_stop=1395.0, trailing_active=False,
                         pivot_price=1490.0, exit_pending=True, exit_reason="hard_stop",
                         exit_trigger_price=1395.0)
    storage.add_position(position)
    market_data = FakeMarketData(bars={"INFY": Bar(1300.0, 1310.0, 1290.0, 1305.0, 1420.0)})
    executor = FakeExecutor()

    result = process_exits(storage, market_data, executor, "2026-01-06", make_config())

    assert len(result["gap_fills"]) == 1
    assert result["gap_fills"][0]["symbol"] == "INFY"
    assert result["gap_fills"][0]["trigger_price"] == 1395.0
    assert result["gap_fills"][0]["fill_price"] == 1300.0

def test_exit_fill_close_to_trigger_not_flagged_as_gap(storage):
    position = Position(id=None, symbol="TCS", entry_date="2026-01-01", entry_price=3800.0,
                         quantity=5, rs_at_entry=90, hard_stop=3534.0, trailing_active=False,
                         pivot_price=3780.0, exit_pending=True, exit_reason="hard_stop",
                         exit_trigger_price=3534.0)
    storage.add_position(position)
    market_data = FakeMarketData(bars={"TCS": Bar(3530.0, 3540.0, 3520.0, 3535.0, 3600.0)})
    executor = FakeExecutor()

    result = process_exits(storage, market_data, executor, "2026-01-06", make_config())

    assert result["gap_fills"] == []

def test_marks_new_exit_without_executing_same_day(storage):
    position = Position(id=None, symbol="TCS", entry_date="2026-01-01", entry_price=3800.0,
                         quantity=5, rs_at_entry=90, hard_stop=3534.0, trailing_active=False,
                         pivot_price=3780.0)
    storage.add_position(position)
    market_data = FakeMarketData(bars={"TCS": Bar(3500.0, 3520.0, 3480.0, 3500.0, 3600.0)})
    executor = FakeExecutor()

    result = process_exits(storage, market_data, executor, "2026-01-06", make_config())

    assert executor.exit_calls == []
    assert result["newly_marked"][0]["symbol"] == "TCS"
    assert result["newly_marked"][0]["reason"] == "hard_stop"
    updated = storage.get_open_positions()[0]
    assert updated.exit_pending is True
    assert updated.exit_reason == "hard_stop"
    assert updated.exit_trigger_price == 3534.0

def test_updates_trailing_active_flag(storage):
    position = Position(id=None, symbol="WIPRO", entry_date="2026-01-01", entry_price=500.0,
                         quantity=20, rs_at_entry=75, hard_stop=465.0, trailing_active=False,
                         pivot_price=495.0)
    storage.add_position(position)
    market_data = FakeMarketData(bars={"WIPRO": Bar(520.0, 525.0, 515.0, 522.0, 500.0)})
    executor = FakeExecutor()

    process_exits(storage, market_data, executor, "2026-01-06", make_config())

    updated = storage.get_open_positions()[0]
    assert updated.trailing_active is True

def test_data_error_recorded_and_position_untouched(storage):
    position = Position(id=None, symbol="ITC", entry_date="2026-01-01", entry_price=400.0,
                         quantity=25, rs_at_entry=72, hard_stop=372.0, trailing_active=False,
                         pivot_price=395.0)
    storage.add_position(position)
    market_data = FakeMarketData(errors={"ITC"})
    executor = FakeExecutor()

    result = process_exits(storage, market_data, executor, "2026-01-06", make_config())

    assert len(result["data_errors"]) == 1
    assert len(storage.get_open_positions()) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_workflow_exits.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bot.workflow'`

- [ ] **Step 3: Write minimal implementation**

```python
# bot/workflow.py
from bot.market_data import DataUnavailableError
from bot.exit_rules import evaluate_exit
from bot.risk_controls import detect_gap

def process_exits(storage, market_data, executor, today: str, config) -> dict:
    if storage.get_kill_switch():
        return {"executed_exits": [], "newly_marked": [], "gap_fills": [],
                 "data_errors": [], "halted": True}

    positions = storage.get_open_positions()
    executed_exits = []
    gap_fills = []
    newly_marked = []
    data_errors = []

    for position in positions:
        if not position.exit_pending:
            continue
        try:
            bar = market_data.get_daily_bar(position.symbol, today)
        except DataUnavailableError as error:
            data_errors.append(str(error))
            continue

        trade = executor.submit_exit(position, exit_price=bar.open, exit_date=today,
                                      reason=position.exit_reason)
        storage.remove_position(position.id)
        executed_exits.append({"symbol": position.symbol, "exit_price": bar.open,
                                "reason": position.exit_reason, "return_pct": trade.return_pct})
        if detect_gap(position.exit_trigger_price, bar.open, config.gap_threshold_pct):
            gap_fills.append({"symbol": position.symbol,
                               "trigger_price": position.exit_trigger_price,
                               "fill_price": bar.open})

    for position in positions:
        if position.exit_pending:
            continue
        try:
            bar = market_data.get_daily_bar(position.symbol, today)
        except DataUnavailableError as error:
            data_errors.append(str(error))
            continue

        decision = evaluate_exit(position, bar.close, bar.ma_50)
        if decision.trailing_active != position.trailing_active:
            storage.update_position_trailing(position.id, decision.trailing_active)
        if decision.should_exit:
            storage.mark_position_exit_pending(position.id, decision.reason, decision.stop_level)
            newly_marked.append({"symbol": position.symbol, "close": bar.close,
                                  "reason": decision.reason})

    return {"executed_exits": executed_exits, "newly_marked": newly_marked,
            "gap_fills": gap_fills, "data_errors": data_errors, "halted": False}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_workflow_exits.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add bot/workflow.py tests/test_workflow_exits.py
git commit -m "feat: add workflow exit processing (mark on close-breach, fill at next open)"
```

---

### Task 10: Workflow — entry (pending order) processing

**Files:**
- Modify: `bot/workflow.py`
- Test: `tests/test_workflow_entries.py`

**Interfaces:**
- Consumes: `Storage`, `KiteMarketData`/`DataUnavailableError`, `BrokerExecutor`, `detect_gap` (`bot.risk_controls`), `StrategyConfig` (`bot.config`)
- Produces: `process_entries(storage, market_data, executor, today: str, config) -> dict` returning `{"filled": [...], "gap_fills": [...], "data_errors": [...], "halted": bool}`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_workflow_entries.py
import pytest
from bot.storage import Storage
from bot.models import PendingOrder, Position
from bot.market_data import DataUnavailableError
from bot.config import StrategyConfig
from bot.workflow import process_entries

class FakeMarketData:
    def __init__(self, bars=None, errors=None):
        self._bars = bars or {}
        self._errors = errors or set()

    def get_daily_bar(self, symbol, as_of_date):
        if symbol in self._errors:
            raise DataUnavailableError(f"{symbol}: no data")
        return self._bars[symbol]

class Bar:
    def __init__(self, open, high, low, close, ma_50):
        self.open, self.high, self.low, self.close, self.ma_50 = open, high, low, close, ma_50

class FakeExecutor:
    def __init__(self):
        self.entry_calls = []

    def submit_entry(self, symbol, quantity, fill_price, rs_rating, pivot_price, entry_date):
        self.entry_calls.append((symbol, quantity, fill_price))
        return Position(id=1, symbol=symbol, entry_date=entry_date, entry_price=fill_price,
                         quantity=quantity, rs_at_entry=rs_rating, hard_stop=fill_price * 0.93,
                         trailing_active=False, pivot_price=pivot_price)

@pytest.fixture
def storage(tmp_path):
    s = Storage(str(tmp_path / "test.db"))
    yield s
    s.close()

def make_config(**overrides):
    defaults = dict(starting_capital=1000000.0, risk_per_trade_pct=0.01, max_positions=8,
                     position_cap_pct=0.30, hard_stop_pct=0.07, rs_floor=70,
                     pending_order_expiry_sessions=5, daily_loss_limit_pct=0.03,
                     gap_threshold_pct=0.02)
    defaults.update(overrides)
    return StrategyConfig(**defaults)

def test_kill_switch_halts_processing(storage):
    storage.set_kill_switch(True)
    result = process_entries(storage, FakeMarketData(), FakeExecutor(), "2026-01-06",
                              make_config())
    assert result["halted"] is True

def test_fills_when_high_clears_pivot(storage):
    order = PendingOrder(id=None, symbol="INFY", pivot_price=1490.0, rs_at_selection=88,
                          order_date="2026-01-05", quantity=10)
    storage.add_pending_order(order)
    market_data = FakeMarketData(bars={"INFY": Bar(1485.0, 1500.0, 1480.0, 1495.0, 1400.0)})
    executor = FakeExecutor()

    result = process_entries(storage, market_data, executor, "2026-01-06", make_config())

    assert executor.entry_calls == [("INFY", 10, 1490.0)]
    assert result["filled"][0]["fill_price"] == 1490.0
    assert storage.get_pending_orders() == []

def test_fills_at_open_when_gapped_above_pivot_and_flags_gap(storage):
    order = PendingOrder(id=None, symbol="TCS", pivot_price=3780.0, rs_at_selection=90,
                          order_date="2026-01-05", quantity=5)
    storage.add_pending_order(order)
    market_data = FakeMarketData(bars={"TCS": Bar(3900.0, 3920.0, 3890.0, 3910.0, 3600.0)})
    executor = FakeExecutor()

    result = process_entries(storage, market_data, executor, "2026-01-06", make_config())

    assert executor.entry_calls == [("TCS", 5, 3900.0)]
    assert len(result["gap_fills"]) == 1

def test_not_triggered_increments_wait_and_keeps_order(storage):
    order = PendingOrder(id=None, symbol="WIPRO", pivot_price=500.0, rs_at_selection=75,
                          order_date="2026-01-05", quantity=20)
    storage.add_pending_order(order)
    market_data = FakeMarketData(bars={"WIPRO": Bar(480.0, 490.0, 475.0, 485.0, 470.0)})
    executor = FakeExecutor()

    result = process_entries(storage, market_data, executor, "2026-01-06", make_config())

    assert executor.entry_calls == []
    remaining = storage.get_pending_orders()
    assert len(remaining) == 1
    assert remaining[0].sessions_waited == 1

def test_expires_after_configured_sessions(storage):
    order = PendingOrder(id=None, symbol="ITC", pivot_price=400.0, rs_at_selection=72,
                          order_date="2026-01-01", quantity=25, sessions_waited=4)
    storage.add_pending_order(order)
    market_data = FakeMarketData(bars={"ITC": Bar(380.0, 390.0, 375.0, 385.0, 370.0)})
    executor = FakeExecutor()

    process_entries(storage, market_data, executor, "2026-01-06",
                     make_config(pending_order_expiry_sessions=5))

    assert storage.get_pending_orders() == []

def test_data_error_recorded_order_untouched(storage):
    order = PendingOrder(id=None, symbol="HDFC", pivot_price=1700.0, rs_at_selection=80,
                          order_date="2026-01-05", quantity=15)
    storage.add_pending_order(order)
    market_data = FakeMarketData(errors={"HDFC"})
    executor = FakeExecutor()

    result = process_entries(storage, market_data, executor, "2026-01-06", make_config())

    assert len(result["data_errors"]) == 1
    assert len(storage.get_pending_orders()) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_workflow_entries.py -v`
Expected: FAIL with `ImportError: cannot import name 'process_entries' from 'bot.workflow'`

- [ ] **Step 3: Write minimal implementation**

Add to `bot/workflow.py` (below `process_exits`):

```python
from bot.risk_controls import detect_gap

def process_entries(storage, market_data, executor, today: str, config) -> dict:
    if storage.get_kill_switch():
        return {"filled": [], "gap_fills": [], "data_errors": [], "halted": True}

    pending = storage.get_pending_orders()
    filled = []
    gap_fills = []
    data_errors = []

    for order in pending:
        try:
            bar = market_data.get_daily_bar(order.symbol, today)
        except DataUnavailableError as error:
            data_errors.append(str(error))
            continue

        if bar.high >= order.pivot_price:
            fill_price = bar.open if bar.open > order.pivot_price else order.pivot_price
            executor.submit_entry(symbol=order.symbol, quantity=order.quantity,
                                   fill_price=fill_price, rs_rating=order.rs_at_selection,
                                   pivot_price=order.pivot_price, entry_date=today)
            storage.remove_pending_order(order.id)
            filled.append({"symbol": order.symbol, "fill_price": fill_price,
                            "quantity": order.quantity})
            if detect_gap(order.pivot_price, fill_price, config.gap_threshold_pct):
                gap_fills.append({"symbol": order.symbol, "pivot_price": order.pivot_price,
                                   "fill_price": fill_price})
        else:
            storage.increment_pending_order_wait(order.id)
            if order.sessions_waited + 1 >= config.pending_order_expiry_sessions:
                storage.remove_pending_order(order.id)

    return {"filled": filled, "gap_fills": gap_fills, "data_errors": data_errors,
            "halted": False}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_workflow_entries.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add bot/workflow.py tests/test_workflow_entries.py
git commit -m "feat: add workflow pending buy-stop resolution with gap detection"
```

---

### Task 11: Workflow — candidate selection & daily summary

**Files:**
- Modify: `bot/workflow.py`
- Test: `tests/test_workflow_selection.py`

**Interfaces:**
- Consumes: `Storage`, `KiteMarketData`/`DataUnavailableError`, `Candidate` (`bot.models`), `compute_position_size` (`bot.sizing`), `check_daily_loss_limit` (`bot.risk_controls`), `StrategyConfig`
- Produces: `compute_current_equity(storage, market_data, today: str) -> float`, `select_and_queue_candidates(storage, market_data, candidates: list, today: str, config) -> dict`, `build_daily_summary(storage, market_data, today: str, exit_result: dict, entry_result: dict, selection_result: dict, config) -> dict` (now trips the kill switch and reports `daily_loss_limit_breached` when the day's loss exceeds `config.daily_loss_limit_pct`)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_workflow_selection.py
import pytest
from bot.storage import Storage
from bot.models import Candidate, Position, PendingOrder
from bot.market_data import DataUnavailableError
from bot.config import StrategyConfig
from bot.workflow import compute_current_equity, select_and_queue_candidates, build_daily_summary

class FakeMarketData:
    def __init__(self, bars=None, errors=None):
        self._bars = bars or {}
        self._errors = errors or set()

    def get_daily_bar(self, symbol, as_of_date):
        if symbol in self._errors:
            raise DataUnavailableError(f"{symbol}: no data")
        return self._bars[symbol]

class Bar:
    def __init__(self, open, high, low, close, ma_50):
        self.open, self.high, self.low, self.close, self.ma_50 = open, high, low, close, ma_50

@pytest.fixture
def storage(tmp_path):
    s = Storage(str(tmp_path / "test.db"))
    s.set_cash_balance(1000000.0)
    yield s
    s.close()

def make_config(**overrides):
    defaults = dict(starting_capital=1000000.0, risk_per_trade_pct=0.01, max_positions=8,
                     position_cap_pct=0.30, hard_stop_pct=0.07, rs_floor=70,
                     pending_order_expiry_sessions=5, daily_loss_limit_pct=0.03,
                     gap_threshold_pct=0.02)
    defaults.update(overrides)
    return StrategyConfig(**defaults)

def test_compute_current_equity_cash_plus_marked_positions(storage):
    position = Position(id=None, symbol="INFY", entry_date="2026-01-01", entry_price=1500.0,
                         quantity=10, rs_at_entry=88, hard_stop=1395.0, trailing_active=False,
                         pivot_price=1490.0)
    storage.add_position(position)
    storage.set_cash_balance(900000.0)
    market_data = FakeMarketData(bars={"INFY": Bar(1500.0, 1520.0, 1490.0, 1510.0, 1400.0)})

    equity = compute_current_equity(storage, market_data, "2026-01-06")

    assert equity == 900000.0 + 10 * 1510.0

def test_compute_current_equity_falls_back_to_entry_price_on_data_error(storage):
    position = Position(id=None, symbol="ITC", entry_date="2026-01-01", entry_price=400.0,
                         quantity=25, rs_at_entry=72, hard_stop=372.0, trailing_active=False,
                         pivot_price=395.0)
    storage.add_position(position)
    storage.set_cash_balance(990000.0)
    market_data = FakeMarketData(errors={"ITC"})

    equity = compute_current_equity(storage, market_data, "2026-01-06")

    assert equity == 990000.0 + 25 * 400.0

def test_select_and_queue_ranks_by_rs_and_respects_open_slots(storage):
    candidates = [
        Candidate(symbol="A", pivot_price=100.0, rs_rating=80, current_price=101.0, ma_50=90.0),
        Candidate(symbol="B", pivot_price=200.0, rs_rating=95, current_price=201.0, ma_50=180.0),
        Candidate(symbol="C", pivot_price=300.0, rs_rating=72, current_price=301.0, ma_50=280.0),
    ]
    config = make_config(max_positions=2)
    market_data = FakeMarketData()

    result = select_and_queue_candidates(storage, market_data, candidates, "2026-01-06", config)

    selected_symbols = [entry["symbol"] for entry in result["selected"]]
    assert selected_symbols == ["B", "A"]
    assert result["skipped"] == [{"symbol": "C", "rs_rating": 72}]
    queued = storage.get_pending_orders()
    assert {order.symbol for order in queued} == {"A", "B"}

def test_select_and_queue_drops_below_rs_floor_and_already_held(storage):
    storage.add_pending_order(PendingOrder(id=None, symbol="A", pivot_price=100.0,
                                            rs_at_selection=80, order_date="2026-01-05",
                                            quantity=5))
    candidates = [
        Candidate(symbol="A", pivot_price=100.0, rs_rating=80, current_price=101.0, ma_50=90.0),
        Candidate(symbol="D", pivot_price=50.0, rs_rating=60, current_price=51.0, ma_50=45.0),
    ]
    config = make_config(max_positions=8, rs_floor=70)
    market_data = FakeMarketData()

    result = select_and_queue_candidates(storage, market_data, candidates, "2026-01-06", config)

    assert result["selected"] == []
    assert result["skipped"] == []

def test_select_and_queue_no_open_slots_returns_all_skipped(storage):
    for i in range(2):
        storage.add_position(Position(id=None, symbol=f"H{i}", entry_date="2026-01-01",
                                       entry_price=100.0, quantity=1, rs_at_entry=80,
                                       hard_stop=93.0, trailing_active=False, pivot_price=99.0))
    candidates = [
        Candidate(symbol="A", pivot_price=100.0, rs_rating=80, current_price=101.0, ma_50=90.0),
    ]
    config = make_config(max_positions=2)
    market_data = FakeMarketData()

    result = select_and_queue_candidates(storage, market_data, candidates, "2026-01-06", config)

    assert result["selected"] == []
    assert result["skipped"] == [{"symbol": "A", "rs_rating": 80}]

def test_kill_switch_blocks_selection(storage):
    storage.set_kill_switch(True)
    result = select_and_queue_candidates(storage, FakeMarketData(), [], "2026-01-06",
                                          make_config())
    assert result["halted"] is True

def test_build_daily_summary_computes_equity_and_drawdown(storage):
    storage.record_equity("2026-01-01", 1000000.0, 1000000.0)
    market_data = FakeMarketData()

    summary = build_daily_summary(
        storage, market_data, "2026-01-06",
        exit_result={"executed_exits": [], "newly_marked": [], "data_errors": []},
        entry_result={"filled": [], "gap_fills": [], "data_errors": []},
        selection_result={"selected": [], "skipped": []},
        config=make_config(),
    )

    assert summary["current_equity"] == 1000000.0
    assert summary["drawdown_pct"] == 0.0
    assert summary["date"] == "2026-01-06"
    assert summary["daily_loss_limit_breached"] is False
    assert storage.get_kill_switch() is False

def test_build_daily_summary_trips_kill_switch_on_daily_loss_breach(storage):
    storage.record_equity("2026-01-05", 1000000.0, 1000000.0)
    storage.set_cash_balance(950000.0)  # 5% down, breaches default 3% daily_loss_limit_pct
    market_data = FakeMarketData()

    summary = build_daily_summary(
        storage, market_data, "2026-01-06",
        exit_result={"executed_exits": [], "newly_marked": [], "data_errors": []},
        entry_result={"filled": [], "gap_fills": [], "data_errors": []},
        selection_result={"selected": [], "skipped": []},
        config=make_config(daily_loss_limit_pct=0.03),
    )

    assert summary["daily_loss_limit_breached"] is True
    assert storage.get_kill_switch() is True

def test_build_daily_summary_no_prior_equity_does_not_breach(storage):
    market_data = FakeMarketData()

    summary = build_daily_summary(
        storage, market_data, "2026-01-06",
        exit_result={"executed_exits": [], "newly_marked": [], "data_errors": []},
        entry_result={"filled": [], "gap_fills": [], "data_errors": []},
        selection_result={"selected": [], "skipped": []},
        config=make_config(),
    )

    assert summary["daily_loss_limit_breached"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_workflow_selection.py -v`
Expected: FAIL with `ImportError: cannot import name 'compute_current_equity' from 'bot.workflow'`

- [ ] **Step 3: Write minimal implementation**

Add to `bot/workflow.py`:

```python
from bot.models import PendingOrder
from bot.sizing import compute_position_size
from bot.risk_controls import check_daily_loss_limit

def compute_current_equity(storage, market_data, today: str) -> float:
    cash = storage.get_cash_balance()
    market_value = 0.0
    for position in storage.get_open_positions():
        try:
            bar = market_data.get_daily_bar(position.symbol, today)
            market_value += position.quantity * bar.close
        except DataUnavailableError:
            market_value += position.quantity * position.entry_price
    return cash + market_value

def select_and_queue_candidates(storage, market_data, candidates: list, today: str,
                                 config) -> dict:
    if storage.get_kill_switch():
        return {"selected": [], "skipped": [], "halted": True}

    open_positions = storage.get_open_positions()
    pending = storage.get_pending_orders()
    held_symbols = {p.symbol for p in open_positions} | {o.symbol for o in pending}
    open_slots = config.max_positions - len(open_positions) - len(pending)

    eligible = [c for c in candidates
                if c.symbol not in held_symbols and c.rs_rating >= config.rs_floor]
    eligible.sort(key=lambda c: c.rs_rating, reverse=True)

    if open_slots <= 0:
        return {"selected": [],
                "skipped": [{"symbol": c.symbol, "rs_rating": c.rs_rating} for c in eligible],
                "halted": False}

    selected = eligible[:open_slots]
    skipped = eligible[open_slots:]
    equity = compute_current_equity(storage, market_data, today)

    queued = []
    for candidate in selected:
        quantity = compute_position_size(equity, candidate.pivot_price,
                                          risk_pct=config.risk_per_trade_pct,
                                          stop_pct=config.hard_stop_pct,
                                          position_cap_pct=config.position_cap_pct)
        if quantity <= 0:
            continue
        order = PendingOrder(id=None, symbol=candidate.symbol, pivot_price=candidate.pivot_price,
                              rs_at_selection=candidate.rs_rating, order_date=today,
                              quantity=quantity)
        storage.add_pending_order(order)
        queued.append({"symbol": candidate.symbol, "quantity": quantity,
                        "pivot_price": candidate.pivot_price})

    return {"selected": queued,
            "skipped": [{"symbol": c.symbol, "rs_rating": c.rs_rating} for c in skipped],
            "halted": False}

def build_daily_summary(storage, market_data, today: str, exit_result: dict,
                         entry_result: dict, selection_result: dict, config) -> dict:
    previous = storage.get_latest_equity()  # (equity, cash) as of the last recorded day, or None
    equity = compute_current_equity(storage, market_data, today)
    peak = max(storage.get_equity_peak(), equity)
    storage.record_equity(today, equity, storage.get_cash_balance())
    drawdown_pct = 0.0 if peak == 0 else (peak - equity) / peak * 100

    daily_loss_limit_breached = False
    if previous is not None:
        previous_equity, _previous_cash = previous
        daily_loss_limit_breached = check_daily_loss_limit(
            previous_equity, equity, config.daily_loss_limit_pct
        )
        if daily_loss_limit_breached:
            storage.set_kill_switch(True)

    return {
        "date": today,
        "entries_filled": entry_result.get("filled", []),
        "gap_fills": entry_result.get("gap_fills", []),
        "exits_executed": exit_result.get("executed_exits", []),
        "exits_marked": exit_result.get("newly_marked", []),
        "exit_gap_fills": exit_result.get("gap_fills", []),
        "candidates_queued": selection_result.get("selected", []),
        "candidates_skipped": selection_result.get("skipped", []),
        "data_errors": exit_result.get("data_errors", []) + entry_result.get("data_errors", []),
        "current_equity": equity,
        "drawdown_pct": drawdown_pct,
        "daily_loss_limit_breached": daily_loss_limit_breached,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_workflow_selection.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add bot/workflow.py tests/test_workflow_selection.py
git commit -m "feat: add candidate selection, sizing, and daily summary to workflow"
```

---

### Task 12: Console CLI, entrypoint, and setup docs

**Files:**
- Create: `bot/cli.py`
- Create: `main.py`
- Create: `README.md`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: everything from Tasks 1–11, plus `reconcile_positions` (`bot.risk_controls`)
- Produces: `print_summary(summary: dict, print_fn=print) -> None`, `run_daily_cycle(storage, market_data, executor, strategy_config, input_fn=input, print_fn=print) -> dict` (runs a reconciliation check first and halts with an alert instead of proceeding if it finds problems), `refresh_kite_access_token(kite_client, kite_config, input_fn=input, print_fn=print) -> None`, `main_menu(storage, market_data, executor, strategy_config, kite_client, kite_config, input_fn=input, print_fn=print) -> None`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli.py
import pytest
from bot.storage import Storage
from bot.config import StrategyConfig
from bot.cli import run_daily_cycle, main_menu, print_summary

class FakeMarketData:
    def get_daily_bar(self, symbol, as_of_date):
        raise AssertionError("not used in this test")

class FakeExecutor:
    pass

@pytest.fixture
def storage(tmp_path):
    s = Storage(str(tmp_path / "test.db"))
    s.set_cash_balance(1000000.0)
    yield s
    s.close()

def make_config(**overrides):
    defaults = dict(starting_capital=1000000.0, risk_per_trade_pct=0.01, max_positions=8,
                     position_cap_pct=0.30, hard_stop_pct=0.07, rs_floor=70,
                     pending_order_expiry_sessions=5, daily_loss_limit_pct=0.03,
                     gap_threshold_pct=0.02)
    defaults.update(overrides)
    return StrategyConfig(**defaults)

def test_run_daily_cycle_with_no_open_positions_and_no_candidates(storage):
    inputs = iter(["done"])
    prints = []

    summary = run_daily_cycle(
        storage, FakeMarketData(), FakeExecutor(), make_config(),
        input_fn=lambda _: next(inputs), print_fn=prints.append,
    )

    assert summary["entries_filled"] == []
    assert summary["exits_executed"] == []
    assert summary["current_equity"] == 1000000.0
    assert any("Daily Summary" in message for message in prints)

def test_run_daily_cycle_halts_on_reconciliation_problem(storage):
    from bot.models import Position
    bad_position = Position(id=None, symbol="BAD", entry_date="2026-01-01", entry_price=100.0,
                             quantity=0, rs_at_entry=80, hard_stop=93.0, trailing_active=False,
                             pivot_price=99.0)
    storage.add_position(bad_position)

    def fail_if_called(_prompt):
        raise AssertionError("should not prompt for candidates when reconciliation halts")

    prints = []

    summary = run_daily_cycle(
        storage, FakeMarketData(), FakeExecutor(), make_config(),
        input_fn=fail_if_called, print_fn=prints.append,
    )

    assert summary["halted"] is True
    assert any("RECONCILIATION" in message for message in prints)
    remaining = storage.get_open_positions()
    assert len(remaining) == 1
    assert remaining[0].quantity == 0  # untouched, not silently dropped or corrected

def test_print_summary_includes_key_fields():
    prints = []
    print_summary({
        "date": "2026-01-06", "current_equity": 1000000.0, "drawdown_pct": 0.0,
        "entries_filled": [], "gap_fills": [], "exits_executed": [], "exits_marked": [],
        "exit_gap_fills": [], "candidates_queued": [], "candidates_skipped": [],
        "data_errors": [], "daily_loss_limit_breached": False,
    }, print_fn=prints.append)
    assert any("2026-01-06" in message for message in prints)
    assert any("1000000" in message for message in prints)

def test_main_menu_view_positions_then_exit(storage):
    inputs = iter(["2", "5"])
    prints = []

    main_menu(storage, FakeMarketData(), FakeExecutor(), make_config(),
               kite_client=None, kite_config=None,
               input_fn=lambda _: next(inputs), print_fn=prints.append)

    assert any("1) Run daily cycle" in message for message in prints)

def test_main_menu_toggle_kill_switch(storage):
    inputs = iter(["4", "5"])
    prints = []

    main_menu(storage, FakeMarketData(), FakeExecutor(), make_config(),
               kite_client=None, kite_config=None,
               input_fn=lambda _: next(inputs), print_fn=prints.append)

    assert storage.get_kill_switch() is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bot.cli'`

- [ ] **Step 3: Write minimal implementation**

```python
# bot/cli.py
from datetime import date
from bot.candidate_input import prompt_for_candidates
from bot.risk_controls import reconcile_positions
from bot.workflow import process_exits, process_entries, select_and_queue_candidates, build_daily_summary

def print_summary(summary: dict, print_fn=print) -> None:
    print_fn(f"\n=== Daily Summary: {summary['date']} ===")
    print_fn(f"Equity: {summary['current_equity']:.2f}  Drawdown: {summary['drawdown_pct']:.2f}%")
    print_fn(f"Entries filled: {summary['entries_filled']}")
    print_fn(f"Gap fills: {summary['gap_fills']}")
    print_fn(f"Exits executed: {summary['exits_executed']}")
    print_fn(f"Exits newly marked (fill next session): {summary['exits_marked']}")
    if summary["exit_gap_fills"]:
        print_fn(f"GAP ALERT (exit filled worse than trigger): {summary['exit_gap_fills']}")
    print_fn(f"Candidates queued: {summary['candidates_queued']}")
    print_fn(f"Candidates skipped (book full): {summary['candidates_skipped']}")
    if summary["data_errors"]:
        print_fn(f"DATA ERRORS: {summary['data_errors']}")
    if summary.get("daily_loss_limit_breached"):
        print_fn("ALERT: daily loss limit breached. Kill switch has been turned ON.")

def run_daily_cycle(storage, market_data, executor, strategy_config,
                     input_fn=input, print_fn=print) -> dict:
    today = date.today().isoformat()

    problems = reconcile_positions(storage.get_open_positions())
    if problems:
        print_fn("RECONCILIATION HALT: internal position log looks inconsistent. "
                  "No orders will be placed until a human resolves this.")
        for problem in problems:
            print_fn(f"  - {problem}")
        return {"halted": True, "reconciliation_problems": problems}

    exit_result = process_exits(storage, market_data, executor, today, strategy_config)
    entry_result = process_entries(storage, market_data, executor, today, strategy_config)

    if not entry_result["halted"]:
        print_fn("Enter today's Fresh Breakout candidates for open slots.")
        candidates = prompt_for_candidates(input_fn, print_fn)
        selection_result = select_and_queue_candidates(
            storage, market_data, candidates, today, strategy_config
        )
    else:
        selection_result = {"selected": [], "skipped": [], "halted": True}

    summary = build_daily_summary(storage, market_data, today, exit_result, entry_result,
                                   selection_result, strategy_config)
    print_summary(summary, print_fn)
    return summary

def refresh_kite_access_token(kite_client, kite_config, input_fn=input, print_fn=print) -> None:
    from bot.config import save_access_token

    print_fn(f"Open this URL, log in, and copy the request_token from the redirect URL:")
    print_fn(kite_client.login_url())
    request_token = input_fn("Paste request_token: ").strip()
    session = kite_client.generate_session(request_token, api_secret=kite_config.api_secret)
    access_token = session["access_token"]
    kite_client.set_access_token(access_token)
    save_access_token(access_token)
    print_fn("Access token refreshed and saved to .env.")

def main_menu(storage, market_data, executor, strategy_config, kite_client, kite_config,
              input_fn=input, print_fn=print) -> None:
    while True:
        print_fn("\n0) Refresh Kite login token  1) Run daily cycle  2) View positions  "
                  "3) View trade log  4) Toggle kill switch  5) Exit")
        choice = input_fn("Choose: ").strip()
        if choice == "0":
            refresh_kite_access_token(kite_client, kite_config, input_fn, print_fn)
        elif choice == "1":
            run_daily_cycle(storage, market_data, executor, strategy_config, input_fn, print_fn)
        elif choice == "2":
            positions = storage.get_open_positions()
            if not positions:
                print_fn("No open positions.")
            for position in positions:
                print_fn(position)
        elif choice == "3":
            trades = storage.get_trade_log()
            if not trades:
                print_fn("No closed trades yet.")
            for trade in trades:
                print_fn(trade)
        elif choice == "4":
            current = storage.get_kill_switch()
            storage.set_kill_switch(not current)
            print_fn(f"Kill switch is now {'ON' if not current else 'OFF'}")
        elif choice == "5":
            break
        else:
            print_fn("Invalid choice, try again.")
```

```python
# main.py
from kiteconnect import KiteConnect
from bot.config import load_dotenv_if_present, load_strategy_config, load_kite_config
from bot.storage import Storage
from bot.market_data import KiteMarketData
from bot.broker_executor import PaperExecutor
from bot.cli import main_menu

def main():
    load_dotenv_if_present()
    strategy_config = load_strategy_config()
    kite_config = load_kite_config()

    kite_client = KiteConnect(api_key=kite_config.api_key)
    if kite_config.access_token:
        kite_client.set_access_token(kite_config.access_token)

    storage = Storage("bot_state.db")
    if storage.get_latest_equity() is None:
        storage.set_cash_balance(strategy_config.starting_capital)
        storage.record_equity("start", strategy_config.starting_capital,
                               strategy_config.starting_capital)

    market_data = KiteMarketData(kite_client)
    executor = PaperExecutor(storage)

    try:
        main_menu(storage, market_data, executor, strategy_config, kite_client, kite_config)
    finally:
        storage.close()

if __name__ == "__main__":
    main()
```

Create `README.md`:

```markdown
# Blue Sky Breakout Bot (Paper Trading)

Console bot implementing the Blue Sky breakout strategy from
`blue-sky-breakout-bot-spec.md`. **Paper trading only** — no live orders are
placed in this phase.

## Setup

1. `pip install -r requirements.txt`
2. Register an app at https://developers.kite.trade to get a Kite Connect
   API key and secret (requires an active Kite Connect subscription).
3. Copy `.env.example` to `.env` and fill in `KITE_API_KEY` / `KITE_API_SECRET`.
4. `python main.py`, then choose `0) Refresh Kite login token` — this opens a
   login URL, you log in via Zerodha in your browser, then paste the
   `request_token` from the redirect URL back into the console. This is
   required once per day (Kite access tokens expire daily).
5. Choose `1) Run daily cycle` each evening after market close. You'll be
   prompted to type in that day's Blue Sky Fresh Breakout candidates
   (symbol, pivot price, RS rating, current price, 50-day MA) as read from
   bananapatterns.com yourself.

## What this does NOT do (yet)

- Place live orders — `KiteLiveExecutor` is a stub.
- Scrape or automate access to bananapatterns.com.
- Model taxes, brokerage, or slippage in simulated P&L.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Run the full test suite**

Run: `pytest -v`
Expected: PASS (all tests across all tasks — 77 tests, 0 failures)

- [ ] **Step 6: Commit**

```bash
git add bot/cli.py main.py README.md tests/test_cli.py
git commit -m "feat: add console CLI, entrypoint, and setup documentation"
```

---

## Post-implementation notes for the user

- Before running for real, you need your own Kite Connect API key/secret
  (paid Zerodha developer subscription) and to complete the daily login flow
  (menu option `0`).
- The bot starts with `starting_capital` (₹10,00,000 default) as simulated
  cash the first time it runs (no existing equity history in `bot_state.db`).
- Delete `bot_state.db` to reset the paper-trading book from scratch.
- Per source-spec §6, run this in paper mode for at least a full quarter
  before considering live capital, and treat `KiteLiveExecutor` as a
  separate future project requiring its own design/plan cycle.
