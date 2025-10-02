# main.py

from trade_bot.backtest.backtest_engine import BacktestRunner
from trade_bot.data.openbb_provider import OpenBBProvider
from trade_bot.strategy.bollinger_band_strategy import BollingerBandStrategy
from trade_bot.strategy.divergence_strategy import DivergenceStrategy
from trade_bot.strategy.fib_strategy import FibonacciStrategy
from trade_bot.strategy.ma_strategy import MAStrategy  # Assuming you saved the runner class separately

# Example usage
def main():
    # Define your symbols and strategy
    symbols = ["PLTR"]
    provider = OpenBBProvider()

    # Initialize the runner
    runner = BacktestRunner(
        strategy_class=BollingerBandStrategy,
        symbols=symbols,
        provider=provider,
        interval="1d",
        lookback_days=365,
        initial_cash=100000
    )

    # Run the backtest
    runner.run()
    # Visualize results
    runner.visualize()

if __name__ == "__main__":
    main()
