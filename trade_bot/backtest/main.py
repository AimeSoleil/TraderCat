# main.py

from trade_bot.backtest.backtest_engine import BacktestRunner
from trade_bot.data.openbb_provider import OpenBBProvider
from trade_bot.strategy.bollinger_band_strategy import BollingerBandStrategy, make_bb_presets
from trade_bot.strategy.divergence_strategy import DivergenceStrategy, make_divergence_presets
from trade_bot.strategy.fib_strategy import FibonacciStrategy, make_fib_presets
from trade_bot.strategy.ma_strategy import MAStrategy, make_ma_presets

# Example usage
def run_with_single_strategy():
    # Define your symbols and strategy
    symbols = ["PLTR"]
    data_provider = OpenBBProvider()
    # strategy = DivergenceStrategy(
    #     data_provider=data_provider, 
    #     **make_divergence_presets()["short_quick"]
    # )
    # strategy = FibonacciStrategy(
    #     data_provider=data_provider,
    #     **make_fib_presets()["short_quick"]
    # )
    strategy = MAStrategy(
        data_provider=data_provider,
        **make_ma_presets()["short_quick"]
    )
    # strategy = BollingerBandStrategy(
    #     data_provider=data_provider,
    #     **make_bb_presets()["short_quick"]
    # )

    # Initialize the runner
    runner = BacktestRunner(
        strategy=strategy,
        symbols=symbols,
        provider=data_provider,
        interval="1d",
        lookback_days=max(365, strategy.get_lookback_window() * 2),  # Ensure sufficient data
        initial_cash=100000,
    )

    # Run the backtest
    runner.run()
    # Visualize results
    runner.visualize()

if __name__ == "__main__":
    run_with_single_strategy()
