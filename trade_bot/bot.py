from trade_bot.data.openbb_provider import OpenBBProvider
from trade_bot.strategy.divergence_strategy import DivergenceStrategy
from trade_bot.strategy.hidden_divergence_strategy import HiddenDivergenceStrategy
from trade_bot.strategy.signal_model import SignalModel

class TradeBot:
    def __init__(self, executor, symbol):
        self.executor = executor
        self.symbol = symbol

    async def run(self):
        print(f'Running bot for symbol: {self.symbol}...')
        print('Initializing data provider...')
        data_provider = OpenBBProvider()

        # Initialize strategies with the data provider and support adding more strategies per need
        strategies = [
            DivergenceStrategy(data_provider=data_provider), 
            HiddenDivergenceStrategy(data_provider=data_provider)
        ]

        # Fetch basic price data (e.g., last 30 days of daily data); 
        # Strategies can fetch more as needed internally using the shared data provider
        price_data = data_provider.get_price_data(self.symbol, interval="1d", lookback=30)
        print(f"Fetched {len(price_data)} price data points for {self.symbol}: {price_data[-1] if price_data else 'No price data'}")

        signals = [strategy.generate_signal(self.symbol, price_data) for strategy in strategies]
        final_signal_list = self.aggregate_signals(signals)

        self.executor.execute_trade(final_signal_list, self.symbol)

        yield final_signal_list

    def aggregate_signals(self, signals: list[SignalModel]) -> list[SignalModel]:
        # Reserve logic for future improvements
        return signals