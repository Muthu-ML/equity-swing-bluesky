from dataclasses import dataclass
from bot.models import Position

@dataclass
class ExitDecision:
    should_exit: bool
    trailing_active: bool
    stop_level: float
    reason: str | None

def evaluate_exit(position: Position, today_close: float, today_50dma: float) -> ExitDecision:
    trailing_active = position.trailing_active or (today_close > today_50dma)

    if trailing_active:
        should_exit = today_close < today_50dma
        stop_level = today_50dma
        reason = "trailing_ma" if should_exit else None
    else:
        should_exit = today_close < position.hard_stop
        stop_level = position.hard_stop
        reason = "hard_stop" if should_exit else None

    return ExitDecision(should_exit, trailing_active, stop_level, reason)
