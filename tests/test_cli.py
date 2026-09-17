import pytest
from bot.storage import Storage
from bot.config import StrategyConfig
from bot.cli import run_daily_cycle, main_menu, print_summary

class FakeMarketData:
    def get_daily_bar(self, symbol, as_of_date):
        raise AssertionError("not used in this test")

class FakeExecutor:
    pass

def fail_if_called(_prompt):
    raise AssertionError("should not prompt for input in this scenario")

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
                     gap_threshold_pct=0.02,
                     candidates_file_path="test_no_candidates_file.csv")
    defaults.update(overrides)
    return StrategyConfig(**defaults)

def write_csv(path, rows, header="symbol,pivot_price,rs_rating"):
    with open(path, "w", newline="") as f:
        f.write(header + "\n")
        for row in rows:
            f.write(row + "\n")

def test_run_daily_cycle_with_no_open_positions_and_no_candidates(storage):
    prints = []

    summary = run_daily_cycle(
        storage, FakeMarketData(), FakeExecutor(), make_config(),
        input_fn=fail_if_called, print_fn=prints.append,
    )

    assert summary["entries_filled"] == []
    assert summary["exits_executed"] == []
    assert summary["current_equity"] == 1000000.0
    assert any("Daily Summary" in message for message in prints)
    assert any("No candidates file found" in message for message in prints)

def test_run_daily_cycle_reads_candidates_from_configured_file(storage, tmp_path):
    file_path = str(tmp_path / "candidates.csv")
    write_csv(file_path, ["INFY,1490.0,88"])
    config = make_config(candidates_file_path=file_path)

    summary = run_daily_cycle(
        storage, FakeMarketData(), FakeExecutor(), config,
        input_fn=fail_if_called, print_fn=lambda _: None,
    )

    # equity=1,000,000; risk_amount=10,000; position_value=10,000/0.07=142,857.14
    # (cap of 300,000 doesn't bind); quantity=floor(142,857.14/1490)=95
    assert summary["candidates_queued"] == [
        {"symbol": "INFY", "quantity": 95, "pivot_price": 1490.0}
    ]
    pending = storage.get_pending_orders()
    assert len(pending) == 1
    assert pending[0].symbol == "INFY"

def test_run_daily_cycle_halts_on_reconciliation_problem(storage):
    from bot.models import Position
    bad_position = Position(id=None, symbol="BAD", entry_date="2026-01-01", entry_price=100.0,
                             quantity=0, rs_at_entry=80, hard_stop=93.0, trailing_active=False,
                             pivot_price=99.0)
    storage.add_position(bad_position)

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

def test_run_daily_cycle_second_run_same_day_aborts_without_confirmation(storage):
    config = make_config()

    # First run establishes today's equity record.
    run_daily_cycle(storage, FakeMarketData(), FakeExecutor(), config,
                     input_fn=fail_if_called, print_fn=lambda _: None)

    call_count = {"n": 0}

    def confirm_then_fail(_prompt):
        call_count["n"] += 1
        if call_count["n"] > 1:
            raise AssertionError("should not prompt again after aborting same-day rerun")
        return "no"

    prints = []
    result = run_daily_cycle(
        storage, FakeMarketData(), FakeExecutor(), config,
        input_fn=confirm_then_fail, print_fn=prints.append,
    )

    assert result == {"halted": True, "already_ran_today": True}
    assert any("Aborted" in message for message in prints)
    assert call_count["n"] == 1  # never reached candidate reading or beyond

def test_run_daily_cycle_second_run_same_day_proceeds_with_yes_confirmation(storage):
    config = make_config()

    run_daily_cycle(storage, FakeMarketData(), FakeExecutor(), config,
                     input_fn=fail_if_called, print_fn=lambda _: None)

    second_inputs = iter(["yes"])
    prints = []
    result = run_daily_cycle(
        storage, FakeMarketData(), FakeExecutor(), config,
        input_fn=lambda _: next(second_inputs), print_fn=prints.append,
    )

    assert "already_ran_today" not in result
    assert result["halted"] is False
    assert any("Daily Summary" in message for message in prints)

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

def test_print_summary_shows_kill_switch_banner_when_new_orders_halted():
    prints = []
    print_summary({
        "date": "2026-01-06", "current_equity": 1000000.0, "drawdown_pct": 0.0,
        "new_orders_halted": True,
        "entries_filled": [], "gap_fills": [], "exits_executed": [], "exits_marked": [],
        "exit_gap_fills": [], "candidates_queued": [], "candidates_skipped": [],
        "data_errors": [], "daily_loss_limit_breached": False,
    }, print_fn=prints.append)
    assert any("KILL SWITCH IS ON" in message for message in prints)

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
