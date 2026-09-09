from kiteconnect import KiteConnect
from bot.config import load_dotenv_if_present, load_strategy_config, load_kite_config
from bot.storage import Storage
from bot.market_data import KiteMarketData
from bot.broker_executor import PaperExecutor
from bot.cli import main_menu

def main():
    load_dotenv_if_present()
    strategy_config = load_strategy_config()
    kite_config = load_kite_config()

    kite_client = KiteConnect(api_key=kite_config.api_key)
    if kite_config.access_token:
        kite_client.set_access_token(kite_config.access_token)

    storage = Storage("bot_state.db")
    if storage.get_latest_equity() is None:
        storage.set_cash_balance(strategy_config.starting_capital)
        storage.record_equity("start", strategy_config.starting_capital,
                               strategy_config.starting_capital)

    market_data = KiteMarketData(kite_client)
    executor = PaperExecutor(storage, hard_stop_pct=strategy_config.hard_stop_pct)

    try:
        main_menu(storage, market_data, executor, strategy_config, kite_client, kite_config)
    finally:
        storage.close()

if __name__ == "__main__":
    main()
