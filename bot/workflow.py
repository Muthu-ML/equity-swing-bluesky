from bot.market_data import DataUnavailableError
from bot.exit_rules import evaluate_exit
from bot.risk_controls import detect_gap
from bot.models import PendingOrder
from bot.sizing import compute_position_size
from bot.risk_controls import check_daily_loss_limit

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

def process_entries(storage, market_data, executor, today: str, config) -> dict:
    if storage.get_kill_switch():
        return {"filled": [], "gap_fills": [], "data_errors": [], "halted": True}

    pending = storage.get_pending_orders()
    filled = []
    gap_fills = []
    data_errors = []

    for order in pending:
        try:
            bar = market_data.get_daily_bar(order.symbol, today)
        except DataUnavailableError as error:
            data_errors.append(str(error))
            continue

        if bar.high >= order.pivot_price:
            fill_price = bar.open if bar.open > order.pivot_price else order.pivot_price
            executor.submit_entry(symbol=order.symbol, quantity=order.quantity,
                                   fill_price=fill_price, rs_rating=order.rs_at_selection,
                                   pivot_price=order.pivot_price, entry_date=today)
            storage.remove_pending_order(order.id)
            filled.append({"symbol": order.symbol, "fill_price": fill_price,
                            "quantity": order.quantity})
            if detect_gap(order.pivot_price, fill_price, config.gap_threshold_pct):
                gap_fills.append({"symbol": order.symbol, "pivot_price": order.pivot_price,
                                   "fill_price": fill_price})
        else:
            storage.increment_pending_order_wait(order.id)
            if order.sessions_waited + 1 >= config.pending_order_expiry_sessions:
                storage.remove_pending_order(order.id)

    return {"filled": filled, "gap_fills": gap_fills, "data_errors": data_errors,
            "halted": False}

def compute_current_equity(storage, market_data, today: str) -> float:
    cash = storage.get_cash_balance()
    market_value = 0.0
    for position in storage.get_open_positions():
        try:
            bar = market_data.get_daily_bar(position.symbol, today)
            market_value += position.quantity * bar.close
        except DataUnavailableError:
            market_value += position.quantity * position.entry_price
    return cash + market_value

def select_and_queue_candidates(storage, market_data, candidates: list, today: str,
                                 config) -> dict:
    if storage.get_kill_switch():
        return {"selected": [], "skipped": [], "halted": True}

    open_positions = storage.get_open_positions()
    pending = storage.get_pending_orders()
    held_symbols = {p.symbol for p in open_positions} | {o.symbol for o in pending}
    open_slots = config.max_positions - len(open_positions) - len(pending)

    eligible = [c for c in candidates
                if c.symbol not in held_symbols and c.rs_rating >= config.rs_floor]
    eligible.sort(key=lambda c: c.rs_rating, reverse=True)

    if open_slots <= 0:
        return {"selected": [],
                "skipped": [{"symbol": c.symbol, "rs_rating": c.rs_rating} for c in eligible],
                "halted": False}

    selected = eligible[:open_slots]
    skipped = eligible[open_slots:]
    equity = compute_current_equity(storage, market_data, today)

    queued = []
    for candidate in selected:
        quantity = compute_position_size(equity, candidate.pivot_price,
                                          risk_pct=config.risk_per_trade_pct,
                                          stop_pct=config.hard_stop_pct,
                                          position_cap_pct=config.position_cap_pct)
        if quantity <= 0:
            continue
        order = PendingOrder(id=None, symbol=candidate.symbol, pivot_price=candidate.pivot_price,
                              rs_at_selection=candidate.rs_rating, order_date=today,
                              quantity=quantity)
        storage.add_pending_order(order)
        queued.append({"symbol": candidate.symbol, "quantity": quantity,
                        "pivot_price": candidate.pivot_price})

    return {"selected": queued,
            "skipped": [{"symbol": c.symbol, "rs_rating": c.rs_rating} for c in skipped],
            "halted": False}

def build_daily_summary(storage, market_data, today: str, exit_result: dict,
                         entry_result: dict, selection_result: dict, config) -> dict:
    previous = storage.get_latest_equity()  # (equity, cash) as of the last recorded day, or None
    equity = compute_current_equity(storage, market_data, today)
    peak = max(storage.get_equity_peak(), equity)
    storage.record_equity(today, equity, storage.get_cash_balance())
    drawdown_pct = 0.0 if peak == 0 else (peak - equity) / peak * 100

    daily_loss_limit_breached = False
    if previous is not None:
        previous_equity, _previous_cash = previous
        daily_loss_limit_breached = check_daily_loss_limit(
            previous_equity, equity, config.daily_loss_limit_pct
        )
        if daily_loss_limit_breached:
            storage.set_kill_switch(True)

    return {
        "date": today,
        "entries_filled": entry_result.get("filled", []),
        "gap_fills": entry_result.get("gap_fills", []),
        "exits_executed": exit_result.get("executed_exits", []),
        "exits_marked": exit_result.get("newly_marked", []),
        "exit_gap_fills": exit_result.get("gap_fills", []),
        "candidates_queued": selection_result.get("selected", []),
        "candidates_skipped": selection_result.get("skipped", []),
        "data_errors": exit_result.get("data_errors", []) + entry_result.get("data_errors", []),
        "current_equity": equity,
        "drawdown_pct": drawdown_pct,
        "daily_loss_limit_breached": daily_loss_limit_breached,
    }
