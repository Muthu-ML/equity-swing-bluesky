from bot.models import Candidate

def parse_candidate(raw: dict) -> Candidate:
    symbol = str(raw["symbol"]).strip().upper()
    pivot_price = float(raw["pivot_price"])
    rs_rating = int(raw["rs_rating"])
    current_price = float(raw["current_price"])
    ma_50 = float(raw["ma_50"])

    if pivot_price <= 0:
        raise ValueError("pivot_price must be positive")
    if not (1 <= rs_rating <= 99):
        raise ValueError("rs_rating must be between 1 and 99")
    if current_price <= 0:
        raise ValueError("current_price must be positive")
    if ma_50 <= 0:
        raise ValueError("ma_50 must be positive")

    return Candidate(symbol=symbol, pivot_price=pivot_price, rs_rating=rs_rating,
                      current_price=current_price, ma_50=ma_50)

def prompt_for_candidates(input_fn=input, print_fn=print) -> list[Candidate]:
    print_fn("Enter today's Fresh Breakout candidates. Type 'done' as the symbol to finish.")
    candidates = []
    while True:
        symbol = input_fn("Symbol (or 'done'): ").strip()
        if symbol.upper() == "DONE":
            break
        try:
            pivot_price = input_fn("Pivot price: ")
            rs_rating = input_fn("RS rating (1-99): ")
            current_price = input_fn("Current price: ")
            ma_50 = input_fn("50-day MA: ")
            candidate = parse_candidate({
                "symbol": symbol, "pivot_price": pivot_price, "rs_rating": rs_rating,
                "current_price": current_price, "ma_50": ma_50,
            })
            candidates.append(candidate)
        except (ValueError, KeyError) as error:
            print_fn(f"Invalid input for {symbol}, skipped: {error}")
    return candidates
