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

    def get_latest_equity_date(self) -> str | None:
        row = self._conn.execute(
            "SELECT date FROM equity_history ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return row["date"] if row else None

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
