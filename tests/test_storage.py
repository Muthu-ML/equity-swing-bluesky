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
