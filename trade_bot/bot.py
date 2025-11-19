from regex import P
from trade_bot.data.openbb_provider import OpenBBProvider
from trade_bot.logger.logger import get_logger
from trade_bot.strategy.bbands_breakout_strategy import BollingerBreakoutStrategy, make_bbands_breakout_presets
from trade_bot.strategy.bbands_reversal_strategy import BBandsReversalStrategy, make_bbands_reversal_presets
from trade_bot.strategy.candlestick_reversal_strategy import CandlestickReversalStrategy, make_candlestick_reversal_presets
from trade_bot.strategy.divergence_strategy import DivergenceStrategy, make_divergence_presets
from trade_bot.strategy.fibonacci_retracement_strategy import FibonacciRetracementStrategy, make_fibonacci_presets
from trade_bot.strategy.momentum_strategy import MomentumTrendStrategy, make_momentum_presets
from trade_bot.strategy.signal_model import SignalModel

logger = get_logger(__name__)

class TradeBot:
    def __init__(self, executor, symbol):
        self.executor = executor
        self.symbol = symbol

    async def run(self):
        logger.info(f'Running bot for symbol: {self.symbol}...')
        data_provider = OpenBBProvider()

        # Initialize strategies with the data provider and support adding more strategies per need
        strategies = [
            BollingerBreakoutStrategy(data_provider=data_provider, **make_bbands_breakout_presets()['swing']),
            BBandsReversalStrategy(data_provider=data_provider, **make_bbands_reversal_presets()['swing']),
            DivergenceStrategy(data_provider=data_provider, **make_divergence_presets()['swing']),
            CandlestickReversalStrategy(data_provider=data_provider, **make_candlestick_reversal_presets()['swing']),
            FibonacciRetracementStrategy(data_provider=data_provider, **make_fibonacci_presets()['swing']),
            MomentumTrendStrategy(data_provider=data_provider, **make_momentum_presets()['swing']),
        ]

        # Fetch basic candles (e.g., last 30 days of candles); 
        # Strategies can fetch more as needed internally using the shared data provider
        # Calculate the largest lookback window needed among all strategies
        max_lookback = max(strategy.get_lookback_window() for strategy in strategies)
        candles = data_provider.get_price_data(self.symbol, interval="1d", lookback=max_lookback)
        logger.info(f"Fetched {len(candles)} candles for {self.symbol}: {candles[-1] if candles else 'No candles'}")

        signals = [strategy.generate_signal(self.symbol, candles) for strategy in strategies]
        final_signal_list = self.aggregate_signals(signals)

        self.executor.execute_trade(final_signal_list, self.symbol)

        yield final_signal_list

    def aggregate_signals(self, signals: list[SignalModel]) -> list[SignalModel]:
        # Reserve logic for future improvements
        return signals