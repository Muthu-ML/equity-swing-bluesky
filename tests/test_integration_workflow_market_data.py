import pytest
from bot.storage import Storage
from bot.models import Position
from bot.config import StrategyConfig
from bot.market_data import KiteMarketData
from bot.workflow import process_exits

class FakeKiteClient:
    def __init__(self, instruments, candles):
        self._instruments = instruments
        self._candles = candles

    def instruments(self, exchange):
        return self._instruments

    def historical_data(self, instrument_token, from_date, to_date, interval):
        return self._candles

def make_candles(n, base_close=100.0):
    return [{"open": base_close + i, "high": base_close + i + 1,
             "low": base_close + i - 1, "close": base_close + i}
            for i in range(n)]

@pytest.fixture
def storage(tmp_path):
    s = Storage(str(tmp_path / "test.db"))
    yield s
    s.close()

def make_config(**overrides):
    defaults = dict(starting_capital=1000000.0, risk_per_trade_pct=0.01, max_positions=8,
                     position_cap_pct=0.30, hard_stop_pct=0.07, rs_floor=70,
                     pending_order_expiry_sessions=5, daily_loss_limit_pct=0.03,
                     gap_threshold_pct=0.02, candidates_file_path="candidates.csv")
    defaults.update(overrides)
    return StrategyConfig(**defaults)

class FakeExecutor:
    def submit_exit(self, position, exit_price, exit_date, reason):
        raise AssertionError("not expected to fire in this test")

def test_process_exits_with_real_market_data_and_string_today(storage):
    # Real KiteMarketData against a fake Kite client, called through process_exits's
    # actual string-typed `today` argument — this is the seam Critical Finding #1 broke.
    candles = make_candles(50, base_close=1000.0)  # closes 1000..1049, MA=1024.5
    client = FakeKiteClient(
        instruments=[{"tradingsymbol": "INFY", "instrument_token": 1}],
        candles=candles,
    )
    market_data = KiteMarketData(client)

    position = Position(id=None, symbol="INFY", entry_date="2026-01-01", entry_price=900.0,
                         quantity=10, rs_at_entry=88, hard_stop=837.0, trailing_active=False,
                         pivot_price=890.0)
    storage.add_position(position)

    result = process_exits(storage, market_data, FakeExecutor(), "2026-01-05", make_config())

    assert result["data_errors"] == []
