# main.py

from trade_bot.backtest.backtest_engine import BacktestRunner
from trade_bot.data.openbb_provider import OpenBBProvider
from trade_bot.strategy.bollinger_band_strategy import BollingerBandStrategy
from trade_bot.strategy.divergence_strategy import DivergenceStrategy
from trade_bot.strategy.fib_strategy import FibStrategy
from trade_bot.strategy.hidden_divergence_strategy import HiddenDivergenceStrategy
from trade_bot.strategy.ma_strategy import MAStrategy

# Example usage
def main():
    # Define your symbols and strategy
    symbols = ["NVDA"]
    provider = OpenBBProvider()
    strategy = DivergenceStrategy(provider)
    # strategy = FibStrategy(provider)
    # strategy = MAStrategy(provider)
    # strategy = HiddenDivergenceStrategy(provider)
    # strategy = BollingerBandStrategy(provider)

    # Initialize the runner
    runner = BacktestRunner(
        strategy=strategy,
        symbols=symbols,
        provider=provider,
        interval="1d",
        lookback_days=max(365, strategy.get_lookback_window() * 2), # Ensure sufficient data
        initial_cash=100000
    )

    # Run the backtest
    runner.run()
    # Visualize results
    runner.visualize()

if __name__ == "__main__":
    main()
