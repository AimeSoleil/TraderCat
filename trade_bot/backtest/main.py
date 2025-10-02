# main.py

from trade_bot.backtest.backtest_engine import BacktestRunner
from trade_bot.data.openbb_provider import OpenBBProvider
from trade_bot.strategy.fib_strategy import FibonacciStrategy  # Assuming you saved the runner class separately

# Example usage
def main():
    # Define your symbols and strategy
    symbols = ["AAPL"]
    provider = OpenBBProvider()

    # Initialize the runner
    runner = BacktestRunner(
        strategy_class=FibonacciStrategy,
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
