from bot.market_data import DataUnavailableError
from bot.exit_rules import evaluate_exit
from bot.risk_controls import detect_gap

def process_exits(storage, market_data, executor, today: str, config) -> dict:
    if storage.get_kill_switch():
        return {"executed_exits": [], "newly_marked": [], "gap_fills": [],
                 "data_errors": [], "halted": True}

    positions = storage.get_open_positions()
    executed_exits = []
    gap_fills = []
    newly_marked = []
    data_errors = []

    for position in positions:
        if not position.exit_pending:
            continue
        try:
            bar = market_data.get_daily_bar(position.symbol, today)
        except DataUnavailableError as error:
            data_errors.append(str(error))
            continue

        trade = executor.submit_exit(position, exit_price=bar.open, exit_date=today,
                                      reason=position.exit_reason)
        storage.remove_position(position.id)
        executed_exits.append({"symbol": position.symbol, "exit_price": bar.open,
                                "reason": position.exit_reason, "return_pct": trade.return_pct})
        if detect_gap(position.exit_trigger_price, bar.open, config.gap_threshold_pct):
            gap_fills.append({"symbol": position.symbol,
                               "trigger_price": position.exit_trigger_price,
                               "fill_price": bar.open})

    for position in positions:
        if position.exit_pending:
            continue
        try:
            bar = market_data.get_daily_bar(position.symbol, today)
        except DataUnavailableError as error:
            data_errors.append(str(error))
            continue

        decision = evaluate_exit(position, bar.close, bar.ma_50)
        if decision.trailing_active != position.trailing_active:
            storage.update_position_trailing(position.id, decision.trailing_active)
        if decision.should_exit:
            storage.mark_position_exit_pending(position.id, decision.reason, decision.stop_level)
            newly_marked.append({"symbol": position.symbol, "close": bar.close,
                                  "reason": decision.reason})

    return {"executed_exits": executed_exits, "newly_marked": newly_marked,
            "gap_fills": gap_fills, "data_errors": data_errors, "halted": False}
