import os
import time
import pytest
from datetime import date
from bot.candidate_input import parse_candidate, read_candidates_from_file

def test_parse_candidate_valid():
    candidate = parse_candidate({"symbol": "infy", "pivot_price": 1490.0, "rs_rating": 88})
    assert candidate.symbol == "INFY"
    assert candidate.pivot_price == 1490.0
    assert candidate.rs_rating == 88

def test_parse_candidate_rejects_zero_pivot():
    with pytest.raises(ValueError):
        parse_candidate({"symbol": "X", "pivot_price": 0.0, "rs_rating": 80})

def test_parse_candidate_rejects_out_of_range_rs():
    with pytest.raises(ValueError):
        parse_candidate({"symbol": "X", "pivot_price": 100.0, "rs_rating": 150})
    with pytest.raises(ValueError):
        parse_candidate({"symbol": "X", "pivot_price": 100.0, "rs_rating": 0})

def write_csv(path, rows, header="symbol,pivot_price,rs_rating"):
    with open(path, "w", newline="") as f:
        f.write(header + "\n")
        for row in rows:
            f.write(row + "\n")

def test_read_candidates_from_file_missing_file_returns_empty(tmp_path):
    file_path = str(tmp_path / "candidates.csv")
    prints = []

    candidates = read_candidates_from_file(file_path, "2026-01-05", print_fn=prints.append)

    assert candidates == []
    assert any("No candidates file found" in message for message in prints)

def test_read_candidates_from_file_fresh_file_parses_valid_rows(tmp_path):
    file_path = str(tmp_path / "candidates.csv")
    write_csv(file_path, ["INFY,1490.0,88", "TCS,3780.0,90"])
    today = date.today().isoformat()

    candidates = read_candidates_from_file(file_path, today)

    assert len(candidates) == 2
    assert candidates[0].symbol == "INFY"
    assert candidates[0].pivot_price == 1490.0
    assert candidates[0].rs_rating == 88
    assert candidates[1].symbol == "TCS"

def test_read_candidates_from_file_skips_invalid_row(tmp_path):
    file_path = str(tmp_path / "candidates.csv")
    write_csv(file_path, ["INFY,1490.0,88", "BAD,100.0,150"])
    today = date.today().isoformat()
    prints = []

    candidates = read_candidates_from_file(file_path, today, print_fn=prints.append)

    assert len(candidates) == 1
    assert candidates[0].symbol == "INFY"
    assert any("Invalid" in message for message in prints)

def test_read_candidates_from_file_stale_file_aborts_without_confirmation(tmp_path):
    file_path = str(tmp_path / "candidates.csv")
    write_csv(file_path, ["INFY,1490.0,88"])
    stale_mtime = time.mktime(date(2020, 1, 1).timetuple())
    os.utime(file_path, (stale_mtime, stale_mtime))
    prompts = []

    candidates = read_candidates_from_file(
        file_path, "2026-01-05",
        input_fn=lambda prompt: prompts.append(prompt) or "no",
        print_fn=lambda message: None,
    )

    assert candidates == []
    assert any("WARNING" in prompt for prompt in prompts)

def test_read_candidates_from_file_stale_file_proceeds_on_yes_confirmation(tmp_path):
    file_path = str(tmp_path / "candidates.csv")
    write_csv(file_path, ["INFY,1490.0,88"])
    stale_mtime = time.mktime(date(2020, 1, 1).timetuple())
    os.utime(file_path, (stale_mtime, stale_mtime))

    candidates = read_candidates_from_file(
        file_path, "2026-01-05", input_fn=lambda _: "yes", print_fn=lambda message: None
    )

    assert len(candidates) == 1
    assert candidates[0].symbol == "INFY"
