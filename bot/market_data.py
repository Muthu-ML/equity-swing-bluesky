from dataclasses import dataclass
from datetime import date, timedelta

class DataUnavailableError(Exception):
    pass

@dataclass
class DailyBar:
    open: float
    high: float
    low: float
    close: float
    ma_50: float

class KiteMarketData:
    def __init__(self, kite_client):
        self._kite = kite_client
        self._token_cache: dict[str, int] = {}

    def resolve_instrument_token(self, symbol: str) -> int:
        if symbol in self._token_cache:
            return self._token_cache[symbol]
        try:
            instruments = self._kite.instruments("NSE")
            for row in instruments:
                self._token_cache[row["tradingsymbol"]] = row["instrument_token"]
        except Exception as error:
            raise DataUnavailableError(f"{symbol}: instrument lookup failed: {error}") from error

        if symbol not in self._token_cache:
            raise DataUnavailableError(f"{symbol}: not found in NSE instrument list")
        return self._token_cache[symbol]

    def get_daily_bar(self, symbol: str, as_of_date: date) -> DailyBar:
        instrument_token = self.resolve_instrument_token(symbol)
        from_date = as_of_date - timedelta(days=90)
        try:
            candles = self._kite.historical_data(instrument_token, from_date, as_of_date, "day")
            if len(candles) < 50:
                raise DataUnavailableError(
                    f"{symbol}: insufficient history ({len(candles)} candles, need 50)"
                )
            last_50 = candles[-50:]
            ma_50 = sum(c["close"] for c in last_50) / 50
            today = candles[-1]
            return DailyBar(open=today["open"], high=today["high"], low=today["low"],
                             close=today["close"], ma_50=ma_50)
        except DataUnavailableError:
            raise
        except Exception as error:
            raise DataUnavailableError(f"{symbol}: historical data fetch failed: {error}") from error
