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
                     gap_threshold_pct=0.02, candidates_file_path="candidates.csv")
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
        Candidate(symbol="A", pivot_price=100.0, rs_rating=80),
        Candidate(symbol="B", pivot_price=200.0, rs_rating=95),
        Candidate(symbol="C", pivot_price=300.0, rs_rating=72),
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
        Candidate(symbol="A", pivot_price=100.0, rs_rating=80),
        Candidate(symbol="D", pivot_price=50.0, rs_rating=60),
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
        Candidate(symbol="A", pivot_price=100.0, rs_rating=80),
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

def test_build_daily_summary_always_includes_halted_false(storage):
    market_data = FakeMarketData()

    summary = build_daily_summary(
        storage, market_data, "2026-01-06",
        exit_result={"executed_exits": [], "newly_marked": [], "data_errors": []},
        entry_result={"filled": [], "gap_fills": [], "data_errors": []},
        selection_result={"selected": [], "skipped": []},
        config=make_config(),
    )

    assert summary["halted"] is False
    assert summary["new_orders_halted"] is False

def test_build_daily_summary_flags_new_orders_halted_when_entries_halted(storage):
    market_data = FakeMarketData()

    summary = build_daily_summary(
        storage, market_data, "2026-01-06",
        exit_result={"executed_exits": [], "newly_marked": [], "data_errors": []},
        entry_result={"filled": [], "gap_fills": [], "data_errors": [], "halted": True},
        selection_result={"selected": [], "skipped": [], "halted": True},
        config=make_config(),
    )

    assert summary["new_orders_halted"] is True
