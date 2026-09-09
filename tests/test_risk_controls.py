from bot.models import Position
from bot.risk_controls import check_daily_loss_limit, detect_gap, reconcile_positions

def test_daily_loss_limit_not_breached():
    assert check_daily_loss_limit(1000000.0, 980000.0, 0.03) is False

def test_daily_loss_limit_breached():
    assert check_daily_loss_limit(1000000.0, 950000.0, 0.03) is True

def test_daily_loss_limit_exactly_at_threshold():
    assert check_daily_loss_limit(1000000.0, 970000.0, 0.03) is True

def test_detect_gap_below_threshold():
    assert detect_gap(trigger_price=1000.0, fill_price=1010.0, gap_threshold_pct=0.02) is False

def test_detect_gap_at_threshold():
    assert detect_gap(trigger_price=1000.0, fill_price=1020.0, gap_threshold_pct=0.02) is True

def test_detect_gap_above_threshold():
    assert detect_gap(trigger_price=1000.0, fill_price=1100.0, gap_threshold_pct=0.02) is True

def make_position(quantity=10, entry_price=100.0):
    return Position(id=1, symbol="X", entry_date="2026-01-01", entry_price=entry_price,
                     quantity=quantity, rs_at_entry=80, hard_stop=93.0,
                     trailing_active=False, pivot_price=99.0)

def test_reconcile_positions_clean():
    assert reconcile_positions([make_position()]) == []

def test_reconcile_positions_flags_bad_quantity():
    problems = reconcile_positions([make_position(quantity=0)])
    assert len(problems) == 1
    assert "X" in problems[0]

def test_reconcile_positions_flags_bad_entry_price():
    problems = reconcile_positions([make_position(entry_price=0.0)])
    assert len(problems) == 1

def test_reconcile_positions_empty_list():
    assert reconcile_positions([]) == []
