import pytest
from datetime import date
from bot.market_data import KiteMarketData, DataUnavailableError

class FakeKiteClient:
    def __init__(self, instruments=None, candles=None, raise_on_historical=False,
                 raise_on_instruments=False):
        self._instruments = instruments or []
        self._candles = candles or []
        self._raise_on_historical = raise_on_historical
        self._raise_on_instruments = raise_on_instruments

    def instruments(self, exchange):
        if self._raise_on_instruments:
            raise RuntimeError("network error")
        return self._instruments

    def historical_data(self, instrument_token, from_date, to_date, interval):
        if self._raise_on_historical:
            raise RuntimeError("rate limited")
        return self._candles

def make_candles(n, base_close=100.0):
    return [{"open": base_close + i, "high": base_close + i + 1,
             "low": base_close + i - 1, "close": base_close + i}
            for i in range(n)]

def test_resolve_instrument_token_found():
    client = FakeKiteClient(instruments=[{"tradingsymbol": "INFY", "instrument_token": 12345}])
    market_data = KiteMarketData(client)
    assert market_data.resolve_instrument_token("INFY") == 12345

def test_resolve_instrument_token_not_found_raises():
    client = FakeKiteClient(instruments=[{"tradingsymbol": "TCS", "instrument_token": 1}])
    market_data = KiteMarketData(client)
    with pytest.raises(DataUnavailableError):
        market_data.resolve_instrument_token("INFY")

def test_resolve_instrument_token_client_error_raises_data_unavailable():
    client = FakeKiteClient(raise_on_instruments=True)
    market_data = KiteMarketData(client)
    with pytest.raises(DataUnavailableError):
        market_data.resolve_instrument_token("INFY")

def test_get_daily_bar_computes_ma_and_returns_today_bar():
    candles = make_candles(50, base_close=100.0)
    client = FakeKiteClient(
        instruments=[{"tradingsymbol": "INFY", "instrument_token": 1}],
        candles=candles,
    )
    market_data = KiteMarketData(client)

    bar = market_data.get_daily_bar("INFY", date(2026, 1, 5))

    expected_ma = sum(c["close"] for c in candles) / 50
    assert bar.close == candles[-1]["close"]
    assert bar.open == candles[-1]["open"]
    assert bar.high == candles[-1]["high"]
    assert bar.low == candles[-1]["low"]
    assert bar.ma_50 == expected_ma

def test_get_daily_bar_insufficient_history_raises():
    candles = make_candles(10)
    client = FakeKiteClient(
        instruments=[{"tradingsymbol": "INFY", "instrument_token": 1}],
        candles=candles,
    )
    market_data = KiteMarketData(client)

    with pytest.raises(DataUnavailableError):
        market_data.get_daily_bar("INFY", date(2026, 1, 5))

def test_get_daily_bar_historical_fetch_error_raises_data_unavailable():
    client = FakeKiteClient(
        instruments=[{"tradingsymbol": "INFY", "instrument_token": 1}],
        raise_on_historical=True,
    )
    market_data = KiteMarketData(client)

    with pytest.raises(DataUnavailableError):
        market_data.get_daily_bar("INFY", date(2026, 1, 5))

def test_resolve_instrument_token_cached_after_first_lookup():
    client = FakeKiteClient(instruments=[{"tradingsymbol": "INFY", "instrument_token": 1}])
    market_data = KiteMarketData(client)
    market_data.resolve_instrument_token("INFY")
    client._instruments = []  # simulate the API becoming unavailable
    assert market_data.resolve_instrument_token("INFY") == 1
