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
                     gap_threshold_pct=0.02, candidates_file_path="candidates.csv")
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

def test_kill_switch_does_not_halt_exit_processing(storage):
    # Kill switch halts NEW order placement (entries/candidate selection) only, per
    # source-spec §6 — exits must keep being evaluated/executed even when it's on.
    position = Position(id=None, symbol="INFY", entry_date="2026-01-01", entry_price=1500.0,
                         quantity=10, rs_at_entry=88, hard_stop=1395.0, trailing_active=False,
                         pivot_price=1490.0, exit_pending=True, exit_reason="hard_stop",
                         exit_trigger_price=1395.0)
    storage.add_position(position)
    market_data = FakeMarketData(bars={"INFY": Bar(1380.0, 1390.0, 1370.0, 1385.0, 1420.0)})
    executor = FakeExecutor()
    storage.set_kill_switch(True)

    result = process_exits(storage, market_data, executor, "2026-01-06", make_config())

    assert result["halted"] is False
    assert executor.exit_calls == [("INFY", 1380.0, "hard_stop")]
    assert result["executed_exits"][0]["exit_price"] == 1380.0
    assert storage.get_open_positions() == []

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
