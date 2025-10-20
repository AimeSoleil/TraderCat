from regex import P
from trade_bot.data.openbb_provider import OpenBBProvider
from trade_bot.strategy.bollinger_band_strategy import BollingerBandStrategy, make_bb_presets
from trade_bot.strategy.divergence_strategy import DivergenceStrategy, make_divergence_presets
from trade_bot.strategy.fib_strategy import FibonacciStrategy, make_fib_presets
from trade_bot.strategy.ma_strategy import MAStrategy, make_ma_presets
from trade_bot.strategy.signal_model import SignalModel

class TradeBot:
    def __init__(self, executor, symbol):
        self.executor = executor
        self.symbol = symbol

    async def run(self):
        print(f'Running bot for symbol: {self.symbol}...')
        data_provider = OpenBBProvider()

        # Initialize strategies with the data provider and support adding more strategies per need
        strategies = [
            DivergenceStrategy(data_provider=data_provider, **make_divergence_presets()['short_quick']),
            MAStrategy(data_provider=data_provider, **make_ma_presets()['short_quick']),
            BollingerBandStrategy(data_provider=data_provider, **make_bb_presets()['short_quick']),
            FibonacciStrategy(data_provider=data_provider, **make_fib_presets()['short_quick'])
        ]

        # Fetch basic candles (e.g., last 30 days of candles); 
        # Strategies can fetch more as needed internally using the shared data provider
        # Calculate the largest lookback window needed among all strategies
        max_lookback = max(strategy.get_lookback_window() for strategy in strategies)
        candles = data_provider.get_price_data(self.symbol, interval="1d", lookback=max_lookback)
        print(f"Fetched {len(candles)} candles for {self.symbol}: {candles[-1] if candles else 'No candles'}")

        signals = [strategy.generate_signal(self.symbol, candles) for strategy in strategies]
        final_signal_list = self.aggregate_signals(signals)

        self.executor.execute_trade(final_signal_list, self.symbol)

        yield final_signal_list

    def aggregate_signals(self, signals: list[SignalModel]) -> list[SignalModel]:
        # Reserve logic for future improvements
        return signals