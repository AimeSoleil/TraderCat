# main.py
import threading
import time
import traceback
from tabulate import tabulate
from tqdm import tqdm
from trade_bot.backtest.backtest_engine import BacktestRunner
from trade_bot.data.openbb_provider import OpenBBProvider
from trade_bot.strategy.bbands_breakout_strategy import BollingerBreakoutStrategy, make_bbands_breakout_presets
from trade_bot.strategy.bbands_reversal_strategy import BBandsReversalStrategy, make_bbands_reversal_presets
from trade_bot.strategy.candlestick_reversal_strategy import CandlestickReversalStrategy, make_candlestick_reversal_presets
from trade_bot.strategy.divergence_strategy import DivergenceStrategy, make_divergence_presets
from trade_bot.strategy.fibonacci_retracement_strategy import FibonacciRetracementStrategy, make_fibonacci_presets
from trade_bot.strategy.momentum_strategy import MomentumTrendStrategy, make_momentum_presets
from trade_bot.logger.logger import get_logger
from trade_bot.strategy.sector_rotation_strategy import SectorRotationStrategy

logger = get_logger(__name__)

# 🔧 Configuration
CONFIG = {
    "symbols": ["TSLA"],  # Add more tickers as needed
    "strategies": { # Strategy name to list of preset names
        # "BBBreakout": [
        #     "swing",
        #     "intermediate"
        #     "position"
        # ],
        # "BBReversal": [
        #     "swing",
        #     "intermediate"
        #     "position"
        # ],
        # "Divergence": [
        #     "swing",
        #     "intermediate"
        #     "position"
        # ],
        # "Fibonacci": [
        #     "swing",
        #     "intermediate"
        #     "position"
        # ],
        # "Momentum": [
        #     "swing",
        #     "intermediate"
        #     "position"
        # ],
        
        # "BBBreakout": [
        #     "swing",
        # ],
        # "BBReversal": [
        #     "swing",
        # ],
        # "ReversalCandle": [
        #     "swing",
        # ],
        # "Divergence": [
        #     "swing",
        # ],
        "Fibonacci": [
            "swing",
        ],
        # "Momentum": [
        #     "swing",
        # ],
    },
    "interval": "1d",
    "initial_cash": 100000,
    "save_charts": True,  # Flag to save charts as PNG files
}

def run_configured_presets():
    data_provider = OpenBBProvider()

    strategy_registry = {
        "BBBreakout": (BollingerBreakoutStrategy, make_bbands_breakout_presets()),
        "BBReversal": (BBandsReversalStrategy, make_bbands_reversal_presets()),
        "Divergence": (DivergenceStrategy, make_divergence_presets()),
        "ReversalCandle": (CandlestickReversalStrategy, make_candlestick_reversal_presets()),
        "Fibonacci": (FibonacciRetracementStrategy, make_fibonacci_presets()),
        "Momentum": (MomentumTrendStrategy, make_momentum_presets()),
    }

    total_results = {}
    for strategy_name, preset_names in CONFIG["strategies"].items():
        strategy_class, all_presets = strategy_registry[strategy_name]

        for preset_name in preset_names:
            if preset_name not in all_presets:
                logger.info(
                    f"⚠️ Skipping unknown preset '{preset_name}' for strategy '{strategy_name}'"
                )
                continue

            logger.info("\n" + "=" * 80)
            logger.info(f"🧪 Running backtest for strategy: {strategy_name}")
            logger.info(f"🔧 Using preset: {preset_name}")
            logger.info("=" * 80)

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
                logger.info(f"✅ Finished backtest for {strategy_name} - {preset_name}")
                logger.info(f"⏱ Duration: {duration:.2f} seconds")
            except Exception as e:
                stop_event.set()
                logger.info(f"❌ Error during backtest for {strategy_name} - {preset_name}: {traceback.format_exc()}")

    if total_results:
        print_total_results(total_results)
            
def print_total_results(total_results):
    if total_results is None:
        logger.info("No results to display.")
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
    logger.info("\n📊 Overall Strategy Performance Dashboard")
    logger.info(f"\n{tabulate(table, headers=headers, tablefmt="pretty")}")

def animate_progress_bar(stop_event, prefix='Progress', total=100):
    with tqdm(total=total, desc=prefix, bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt}\n", ncols=70) as p_bar:
        while not stop_event.is_set():
            time.sleep(0.5) # Adjust the sleep time as needed   
            p_bar.update(1)
            if p_bar.n >= total:
                p_bar.n = 0
                p_bar.refresh()
        p_bar.n = total
        p_bar.refresh()

if __name__ == "__main__":
    run_configured_presets()