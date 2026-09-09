from abc import ABC, abstractmethod
from bot.models import Position, Trade
from bot.storage import Storage

class BrokerExecutor(ABC):
    @abstractmethod
    def submit_entry(self, symbol: str, quantity: int, fill_price: float, rs_rating: int,
                      pivot_price: float, entry_date: str) -> Position:
        ...

    @abstractmethod
    def submit_exit(self, position: Position, exit_price: float, exit_date: str,
                     reason: str) -> Trade:
        ...

class PaperExecutor(BrokerExecutor):
    def __init__(self, storage: Storage, hard_stop_pct: float = 0.07):
        self._storage = storage
        self._hard_stop_pct = hard_stop_pct

    def submit_entry(self, symbol: str, quantity: int, fill_price: float, rs_rating: int,
                      pivot_price: float, entry_date: str) -> Position:
        cost = quantity * fill_price
        self._storage.set_cash_balance(self._storage.get_cash_balance() - cost)

        position = Position(
            id=None, symbol=symbol, entry_date=entry_date, entry_price=fill_price,
            quantity=quantity, rs_at_entry=rs_rating,
            hard_stop=fill_price * (1 - self._hard_stop_pct),
            trailing_active=False, pivot_price=pivot_price,
        )
        position.id = self._storage.add_position(position)
        return position

    def submit_exit(self, position: Position, exit_price: float, exit_date: str,
                     reason: str) -> Trade:
        proceeds = position.quantity * exit_price
        self._storage.set_cash_balance(self._storage.get_cash_balance() + proceeds)

        return_pct = (exit_price - position.entry_price) / position.entry_price * 100
        trade = Trade(
            id=None, symbol=position.symbol, entry_date=position.entry_date,
            exit_date=exit_date, entry_price=position.entry_price, exit_price=exit_price,
            quantity=position.quantity, rs_at_entry=position.rs_at_entry,
            return_pct=return_pct, exit_reason=reason,
        )
        self._storage.log_trade(trade)
        self._storage.remove_position(position.id)
        return trade

class KiteLiveExecutor(BrokerExecutor):
    def submit_entry(self, symbol: str, quantity: int, fill_price: float, rs_rating: int,
                      pivot_price: float, entry_date: str) -> Position:
        raise NotImplementedError("Live trading is not implemented in this phase")

    def submit_exit(self, position: Position, exit_price: float, exit_date: str,
                     reason: str) -> Trade:
        raise NotImplementedError("Live trading is not implemented in this phase")
