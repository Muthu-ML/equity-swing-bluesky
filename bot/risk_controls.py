from bot.models import Position

def check_daily_loss_limit(equity_start_of_day: float, equity_now: float, limit_pct: float) -> bool:
    loss_pct = (equity_start_of_day - equity_now) / equity_start_of_day
    return loss_pct >= limit_pct

def detect_gap(trigger_price: float, fill_price: float, gap_threshold_pct: float = 0.02) -> bool:
    return abs(fill_price - trigger_price) / trigger_price >= gap_threshold_pct

def reconcile_positions(positions: list[Position]) -> list[str]:
    problems = []
    for position in positions:
        if position.quantity <= 0:
            problems.append(f"{position.symbol}: non-positive quantity ({position.quantity})")
        elif position.entry_price <= 0:
            problems.append(f"{position.symbol}: non-positive entry price ({position.entry_price})")
    return problems
