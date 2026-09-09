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
