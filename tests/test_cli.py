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

def test_run_daily_cycle_second_run_same_day_aborts_without_confirmation(storage):
    config = make_config()

    # First run establishes today's equity record.
    first_inputs = iter(["done"])
    run_daily_cycle(storage, FakeMarketData(), FakeExecutor(), config,
                     input_fn=lambda _: next(first_inputs), print_fn=lambda _: None)

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
    assert call_count["n"] == 1  # never reached prompt_for_candidates or beyond

def test_run_daily_cycle_second_run_same_day_proceeds_with_yes_confirmation(storage):
    config = make_config()

    first_inputs = iter(["done"])
    run_daily_cycle(storage, FakeMarketData(), FakeExecutor(), config,
                     input_fn=lambda _: next(first_inputs), print_fn=lambda _: None)

    second_inputs = iter(["yes", "done"])
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
