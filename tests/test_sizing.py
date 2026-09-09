import pytest
from bot.sizing import compute_position_size

def test_normal_sizing_not_capped():
    # risk_amount = 1000000 * 0.01 = 10000; position_value = 10000/0.07 = 142857.14
    # cap = 1000000 * 0.30 = 300000, not hit; quantity = floor(142857.14 / 1490)
    quantity = compute_position_size(equity=1000000.0, pivot_price=1490.0)
    assert quantity == 95

def test_position_cap_triggers():
    # For cap to trigger: risk_pct/stop_pct > position_cap_pct
    # With stop_pct=0.01: 0.01/0.01=1.0 > 0.30, so cap triggers
    # uncapped = 50000000*0.01/0.01 = 50000000 > cap = 15000000
    quantity = compute_position_size(equity=50000000.0, pivot_price=100.0, stop_pct=0.01)
    capped_value = 50000000.0 * 0.30
    assert quantity == int(capped_value // 100.0)

def test_quantity_floors_down():
    quantity = compute_position_size(equity=100000.0, pivot_price=333.0)
    risk_amount = 100000.0 * 0.01
    position_value = min(risk_amount / 0.07, 100000.0 * 0.30)
    assert quantity == int(position_value // 333.0)

def test_zero_pivot_price_raises():
    with pytest.raises(ValueError):
        compute_position_size(equity=1000000.0, pivot_price=0.0)

def test_custom_risk_and_cap_params():
    quantity = compute_position_size(
        equity=1000000.0, pivot_price=500.0,
        risk_pct=0.02, stop_pct=0.05, position_cap_pct=0.20,
    )
    risk_amount = 1000000.0 * 0.02
    position_value = min(risk_amount / 0.05, 1000000.0 * 0.20)
    assert quantity == int(position_value // 500.0)
