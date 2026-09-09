import pytest
from bot.candidate_input import parse_candidate, prompt_for_candidates

def test_parse_candidate_valid():
    candidate = parse_candidate({
        "symbol": "infy", "pivot_price": 1490.0, "rs_rating": 88,
        "current_price": 1495.0, "ma_50": 1400.0,
    })
    assert candidate.symbol == "INFY"
    assert candidate.pivot_price == 1490.0
    assert candidate.rs_rating == 88

def test_parse_candidate_rejects_zero_pivot():
    with pytest.raises(ValueError):
        parse_candidate({"symbol": "X", "pivot_price": 0.0, "rs_rating": 80,
                          "current_price": 100.0, "ma_50": 90.0})

def test_parse_candidate_rejects_out_of_range_rs():
    with pytest.raises(ValueError):
        parse_candidate({"symbol": "X", "pivot_price": 100.0, "rs_rating": 150,
                          "current_price": 100.0, "ma_50": 90.0})
    with pytest.raises(ValueError):
        parse_candidate({"symbol": "X", "pivot_price": 100.0, "rs_rating": 0,
                          "current_price": 100.0, "ma_50": 90.0})

def test_parse_candidate_rejects_zero_current_price_or_ma():
    with pytest.raises(ValueError):
        parse_candidate({"symbol": "X", "pivot_price": 100.0, "rs_rating": 80,
                          "current_price": 0.0, "ma_50": 90.0})
    with pytest.raises(ValueError):
        parse_candidate({"symbol": "X", "pivot_price": 100.0, "rs_rating": 80,
                          "current_price": 100.0, "ma_50": 0.0})

def test_prompt_for_candidates_stops_on_done():
    inputs = iter(["done"])
    prints = []
    candidates = prompt_for_candidates(
        input_fn=lambda _: next(inputs), print_fn=prints.append
    )
    assert candidates == []

def test_prompt_for_candidates_collects_one_entry():
    inputs = iter(["INFY", "1490", "88", "1495", "1400", "done"])
    prints = []
    candidates = prompt_for_candidates(
        input_fn=lambda _: next(inputs), print_fn=prints.append
    )
    assert len(candidates) == 1
    assert candidates[0].symbol == "INFY"
    assert candidates[0].rs_rating == 88

def test_prompt_for_candidates_skips_invalid_entry():
    inputs = iter(["BADRS", "100", "150", "100", "90", "done"])
    prints = []
    candidates = prompt_for_candidates(
        input_fn=lambda _: next(inputs), print_fn=prints.append
    )
    assert candidates == []
    assert any("Invalid" in message for message in prints)
