from dataclasses import dataclass, field

@dataclass
class Candidate:
    symbol: str
    pivot_price: float
    rs_rating: int

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
