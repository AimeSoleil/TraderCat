from trade_bot.strategy.signal_model import SignalModel

class TradeBot:
    def __init__(self, data_provider, strategies, executor, symbol):
        self.data_provider = data_provider
        self.strategies = strategies  # List of strategy instances
        self.executor = executor
        self.symbol = symbol

    async def run(self):
        print(f'Running bot for symbol: {self.symbol} with strategies: {[s.get_name() for s in self.strategies]}')
        data = self.data_provider.get_price_data(self.symbol, interval="1d", lookback=30)
        print(f"Fetched {len(data)} data points for {self.symbol}: {data[-1] if data else 'No data'}")

        signals = [strategy.generate_signal(self.symbol, data) for strategy in self.strategies]
        final_signal_list = self.aggregate_signals(signals)

        self.executor.execute_trade(final_signal_list, self.symbol)

        yield final_signal_list

    def aggregate_signals(self, signals: list[SignalModel]) -> list[SignalModel]:
        # Reserve logic for future improvements
        return signals