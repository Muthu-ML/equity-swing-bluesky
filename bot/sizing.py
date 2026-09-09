def compute_position_size(
    equity: float,
    pivot_price: float,
    risk_pct: float = 0.01,
    stop_pct: float = 0.07,
    position_cap_pct: float = 0.30,
) -> int:
    if pivot_price <= 0:
        raise ValueError("pivot_price must be positive")

    risk_amount = equity * risk_pct
    position_value = risk_amount / stop_pct
    position_value = min(position_value, equity * position_cap_pct)
    return int(position_value // pivot_price)
