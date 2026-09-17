import csv
import os
from datetime import datetime
from bot.models import Candidate

def parse_candidate(raw: dict) -> Candidate:
    symbol = str(raw["symbol"]).strip().upper()
    pivot_price = float(raw["pivot_price"])
    rs_rating = int(raw["rs_rating"])

    if pivot_price <= 0:
        raise ValueError("pivot_price must be positive")
    if not (1 <= rs_rating <= 99):
        raise ValueError("rs_rating must be between 1 and 99")

    return Candidate(symbol=symbol, pivot_price=pivot_price, rs_rating=rs_rating)

def read_candidates_from_file(file_path: str, today: str,
                               input_fn=input, print_fn=print) -> list[Candidate]:
    if not os.path.exists(file_path):
        print_fn(
            f"No candidates file found at '{file_path}'. Create it with header "
            f"'symbol,pivot_price,rs_rating' and today's Fresh Breakout candidates, "
            f"then re-run. Proceeding with zero candidates for today."
        )
        return []

    file_date = datetime.fromtimestamp(os.path.getmtime(file_path)).date().isoformat()
    if file_date != today:
        confirm = input_fn(
            f"WARNING: '{file_path}' was last modified on {file_date}, not today ({today}). "
            f"It may contain stale candidates. Type 'yes' to use it anyway, anything else to "
            f"treat today as having zero candidates: "
        )
        if confirm.strip().lower() != "yes":
            print_fn("Skipping candidate entry — file not confirmed as today's data.")
            return []

    candidates = []
    with open(file_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                candidates.append(parse_candidate(row))
            except (ValueError, KeyError) as error:
                symbol = row.get("symbol", "<unknown>")
                print_fn(f"Invalid row for {symbol}, skipped: {error}")
    return candidates
