from datetime import date
from bot.candidate_input import prompt_for_candidates
from bot.risk_controls import reconcile_positions
from bot.workflow import process_exits, process_entries, select_and_queue_candidates, build_daily_summary

def print_summary(summary: dict, print_fn=print) -> None:
    print_fn(f"\n=== Daily Summary: {summary['date']} ===")
    print_fn(f"Equity: {summary['current_equity']:.2f}  Drawdown: {summary['drawdown_pct']:.2f}%")
    print_fn(f"Entries filled: {summary['entries_filled']}")
    print_fn(f"Gap fills: {summary['gap_fills']}")
    print_fn(f"Exits executed: {summary['exits_executed']}")
    print_fn(f"Exits newly marked (fill next session): {summary['exits_marked']}")
    if summary["exit_gap_fills"]:
        print_fn(f"GAP ALERT (exit filled worse than trigger): {summary['exit_gap_fills']}")
    print_fn(f"Candidates queued: {summary['candidates_queued']}")
    print_fn(f"Candidates skipped (book full): {summary['candidates_skipped']}")
    if summary["data_errors"]:
        print_fn(f"DATA ERRORS: {summary['data_errors']}")
    if summary.get("daily_loss_limit_breached"):
        print_fn("ALERT: daily loss limit breached. Kill switch has been turned ON.")

def run_daily_cycle(storage, market_data, executor, strategy_config,
                     input_fn=input, print_fn=print) -> dict:
    today = date.today().isoformat()

    problems = reconcile_positions(storage.get_open_positions())
    if problems:
        print_fn("RECONCILIATION HALT: internal position log looks inconsistent. "
                  "No orders will be placed until a human resolves this.")
        for problem in problems:
            print_fn(f"  - {problem}")
        return {"halted": True, "reconciliation_problems": problems}

    exit_result = process_exits(storage, market_data, executor, today, strategy_config)
    entry_result = process_entries(storage, market_data, executor, today, strategy_config)

    if not entry_result["halted"]:
        print_fn("Enter today's Fresh Breakout candidates for open slots.")
        candidates = prompt_for_candidates(input_fn, print_fn)
        selection_result = select_and_queue_candidates(
            storage, market_data, candidates, today, strategy_config
        )
    else:
        selection_result = {"selected": [], "skipped": [], "halted": True}

    summary = build_daily_summary(storage, market_data, today, exit_result, entry_result,
                                   selection_result, strategy_config)
    print_summary(summary, print_fn)
    return summary

def refresh_kite_access_token(kite_client, kite_config, input_fn=input, print_fn=print) -> None:
    from bot.config import save_access_token

    print_fn(f"Open this URL, log in, and copy the request_token from the redirect URL:")
    print_fn(kite_client.login_url())
    request_token = input_fn("Paste request_token: ").strip()
    session = kite_client.generate_session(request_token, api_secret=kite_config.api_secret)
    access_token = session["access_token"]
    kite_client.set_access_token(access_token)
    save_access_token(access_token)
    print_fn("Access token refreshed and saved to .env.")

def main_menu(storage, market_data, executor, strategy_config, kite_client, kite_config,
              input_fn=input, print_fn=print) -> None:
    while True:
        print_fn("\n0) Refresh Kite login token  1) Run daily cycle  2) View positions  "
                  "3) View trade log  4) Toggle kill switch  5) Exit")
        choice = input_fn("Choose: ").strip()
        if choice == "0":
            refresh_kite_access_token(kite_client, kite_config, input_fn, print_fn)
        elif choice == "1":
            run_daily_cycle(storage, market_data, executor, strategy_config, input_fn, print_fn)
        elif choice == "2":
            positions = storage.get_open_positions()
            if not positions:
                print_fn("No open positions.")
            for position in positions:
                print_fn(position)
        elif choice == "3":
            trades = storage.get_trade_log()
            if not trades:
                print_fn("No closed trades yet.")
            for trade in trades:
                print_fn(trade)
        elif choice == "4":
            current = storage.get_kill_switch()
            storage.set_kill_switch(not current)
            print_fn(f"Kill switch is now {'ON' if not current else 'OFF'}")
        elif choice == "5":
            break
        else:
            print_fn("Invalid choice, try again.")
