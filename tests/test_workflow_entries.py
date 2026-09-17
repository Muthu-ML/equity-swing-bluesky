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
                     gap_threshold_pct=0.02, candidates_file_path="candidates.csv")
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
