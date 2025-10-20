# main.py
import threading
import time
import traceback
from tabulate import tabulate
from tqdm import tqdm
from trade_bot.backtest.backtest_engine import BacktestRunner
from trade_bot.data.openbb_provider import OpenBBProvider
from trade_bot.strategy.bollinger_band_strategy import (
    BollingerBandStrategy,
    make_bb_presets,
)
from trade_bot.strategy.divergence_strategy import (
    DivergenceStrategy,
    make_divergence_presets,
)
from trade_bot.strategy.fib_strategy import FibonacciStrategy, make_fib_presets
from trade_bot.strategy.ma_strategy import MAStrategy, make_ma_presets

# 🔧 Configuration
CONFIG = {
    "symbols": ["PLTR"],  # Add more tickers as needed
    "strategies": { # Strategy name to list of preset names
        # "Divergence": [
        #     "short_quick",
        #     "short_balanced",
        #     "short_conservative",
        #     "mid_aggressive",
        #     "mid_balanced",
        #     "mid_conservative",
        # ],
        # "Fibonacci": [
        #     "short_quick",
        #     "short_balanced",
        #     "short_conservative",
        #     "mid_aggressive",
        #     "mid_balanced",
        #     "mid_conservative",
        # ],
        # "MovingAverage": [
        #     "short_quick",
        #     "short_balanced",
        #     "short_conservative",
        #     "mid_aggressive",
        #     "mid_balanced",
        #     "mid_conservative",
        # ],
        "BollingerBand": [
            "short_quick",
            # "short_balanced",
            # "short_conservative",
            # "mid_aggressive",
            # "mid_balanced",
            # "mid_conservative",
        ],
    },
    "interval": "1d",
    "initial_cash": 100000,
    "save_charts": True,  # Flag to save charts as PNG files
}


def run_configured_presets():
    data_provider = OpenBBProvider()

    strategy_registry = {
        "Divergence": (DivergenceStrategy, make_divergence_presets()),
        "Fibonacci": (FibonacciStrategy, make_fib_presets()),
        "MovingAverage": (MAStrategy, make_ma_presets()),
        "BollingerBand": (BollingerBandStrategy, make_bb_presets()),
    }

    total_results = {}
    for strategy_name, preset_names in CONFIG["strategies"].items():
        strategy_class, all_presets = strategy_registry[strategy_name]

        for preset_name in preset_names:
            if preset_name not in all_presets:
                print(
                    f"⚠️ Skipping unknown preset '{preset_name}' for strategy '{strategy_name}'"
                )
                continue

            print("\n" + "=" * 80)
            print(f"🧪 Running backtest for strategy: {strategy_name}")
            print(f"🔧 Using preset: {preset_name}")
            print("=" * 80)

            try:
                start_time = time.time() # For measuring backtest duration

                strategy = strategy_class(
                    data_provider=data_provider, **all_presets[preset_name]
                )

                runner = BacktestRunner(
                    strategy=strategy,
                    preset_name=preset_name,
                    symbols=CONFIG["symbols"],
                    provider=data_provider,
                    interval=CONFIG["interval"],
                    lookback_days=max(365, strategy.get_lookback_window() * 2),
                    initial_cash=CONFIG["initial_cash"],
                )

                stop_event = threading.Event()
                progress_thread = threading.Thread(target=animate_progress_bar, args=(stop_event,))
                progress_thread.start()

                prefix = f"{strategy_name}_{preset_name}".lower()
                results = runner.run()    # Actual backtest logic
                total_results[prefix] = results

                stop_event.set()
                progress_thread.join()

                runner.visualize(save=CONFIG.get("save_charts", False), output_dir="charts", file_prefix=prefix)

                end_time = time.time()
                duration = end_time - start_time
                print(f"✅ Finished backtest for {strategy_name} - {preset_name}")
                print(f"⏱ Duration: {duration:.2f} seconds")
            except Exception as e:
                print(f"❌ Error during backtest for {strategy_name} - {preset_name}: {traceback.format_exc()}")

    if total_results:
        print_total_results(total_results)
            
def print_total_results(total_results):
    if total_results is None:
        print("No results to display.")
        return
    
    table = []
    for preset_key, results in total_results.items():
        for symbol, result in results.items():
            report = {k: v for k, v in result.items() if k != 'trade_hist'}
            table.append([
                preset_key or "N/A",
                symbol,
                round(report["final_value"], 2),
                round(report["net_profit"], 2),
                report["num_trades"],
                report["win_rate"],
                report["avg_win"],
                report["avg_loss"],
                report["max_drawdown"]
            ])
    headers = ["Preset", "Symbol", "Final Value", "Net Profit", "Trades", "Win Rate", "Avg Win", "Avg Loss", "Max Drawdown"]
    print("\n📊 Overall Strategy Performance Dashboard")
    print(tabulate(table, headers=headers, tablefmt="pretty"))

def animate_progress_bar(stop_event, prefix='Progress', total=100):
    with tqdm(total=total, desc=prefix, bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt}", ncols=70) as pbar:
        while not stop_event.is_set():
            time.sleep(0.5) # Adjust the sleep time as needed   
            pbar.update(1)
            if pbar.n >= total:
                pbar.n = 0
                pbar.refresh()
        pbar.n = total
        pbar.refresh()

if __name__ == "__main__":
    run_configured_presets()
