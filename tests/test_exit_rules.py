from bot.models import Position
from bot.exit_rules import evaluate_exit

def make_position(hard_stop=930.0, trailing_active=False):
    return Position(
        id=1, symbol="TEST", entry_date="2026-01-01", entry_price=1000.0,
        quantity=10, rs_at_entry=80, hard_stop=hard_stop,
        trailing_active=trailing_active, pivot_price=995.0,
    )

def test_not_activated_close_above_hard_stop_no_exit():
    position = make_position()
    decision = evaluate_exit(position, today_close=950.0, today_50dma=900.0)
    assert decision.should_exit is False
    assert decision.trailing_active is False
    assert decision.reason is None

def test_not_activated_close_below_hard_stop_exits():
    position = make_position()
    decision = evaluate_exit(position, today_close=920.0, today_50dma=900.0)
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
