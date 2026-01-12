# main.py
import sys
import os
import time
import traceback
from dataclasses import dataclass, field
from typing import List, Dict
from datetime import datetime
from tabulate import tabulate

# Add project root
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from tradercat.logger.logger import get_logger
from tradercat.data.openbb_provider import OpenBBProvider

# --- Import Strategies ---
from tradercat.strategy.bbands_breakout_strategy import BollingerBreakoutStrategy, make_bbands_breakout_presets
from tradercat.strategy.bbands_reversal_strategy import BBandsReversalStrategy, make_bbands_reversal_presets
from tradercat.strategy.candlestick_reversal_strategy import CandlestickReversalStrategy, make_candlestick_reversal_presets
from tradercat.strategy.divergence_strategy import DivergenceStrategy, make_divergence_presets
from tradercat.strategy.fibonacci_retracement_strategy import FibonacciRetracementStrategy, make_fibonacci_presets
from tradercat.strategy.momentum_strategy import MomentumTrendStrategy, make_momentum_presets
from tradercat.strategy.sector_rotation_strategy import SectorRotationStrategy, make_sector_rotation_presets

# --- Import Runners ---
from tradercat.backtest.backtest_engine import BacktestRunner
from tradercat.backtest.sector_rotation_engine import run_sector_rotation_backtest

logger = get_logger(__name__)

# ==========================================
# 1. Configuration
# ==========================================

@dataclass
class BacktestConfig:
    # Global Settings
    start_date: str = "2025-06-01"
    end_date: str = datetime.now().strftime("%Y-%m-%d")
    initial_cash: float = 100000.0
    save_charts: bool = True
    
    # For Single Asset Strategies (e.g., Momentum, BB)
    # target_symbols: List[str] = field(default_factory=lambda: ["TSLA", "NVDA", "AAPL"])
    target_symbols: List[str] = field(default_factory=lambda: ["TSLA"]) 
    
    # Active Strategies to Run
    # Format: { "StrategyName": ["preset1", "preset2"] }
    active_strategies: Dict[str, List[str]] = field(default_factory=lambda: {
        # --- Single Asset Strategies ---
        # "BBBreakout": ["swing"],
        # "BBReversal": ["swing"],
        # "Divergence": ["swing"],
        "ReversalCandle": ["swing"],
        # "Fibonacci": ["swing"],
        # "Momentum": ["swing"],
        
        # --- Portfolio Strategies ---
        # "SectorRotation": ["swing", "position"], 
    })

# ==========================================
# 2. Strategy Registry
# ==========================================

class StrategyRegistry:
    def __init__(self):
        self._registry = {}

    def register(self, name, cls, preset_func, strat_type="single"):
        """
        strat_type: 
            'single' = Runs on specific symbols (BacktestRunner)
            'portfolio' = Runs on a universe of assets (SectorRotationRunner)
        """
        self._registry[name] = {
            "class": cls,
            "presets": preset_func(),
            "type": strat_type
        }

    def get(self, name):
        return self._registry.get(name)

def setup_registry() -> StrategyRegistry:
    registry = StrategyRegistry()
    
    # Register Single Asset Strategies
    registry.register("BBBreakout", BollingerBreakoutStrategy, make_bbands_breakout_presets, "single")
    registry.register("BBReversal", BBandsReversalStrategy, make_bbands_reversal_presets, "single")
    registry.register("Divergence", DivergenceStrategy, make_divergence_presets, "single")
    registry.register("ReversalCandle", CandlestickReversalStrategy, make_candlestick_reversal_presets, "single")
    registry.register("Fibonacci", FibonacciRetracementStrategy, make_fibonacci_presets, "single")
    registry.register("Momentum", MomentumTrendStrategy, make_momentum_presets, "single")
    
    # Register Portfolio Strategies
    registry.register("SectorRotation", SectorRotationStrategy, make_sector_rotation_presets, "portfolio")
    
    return registry

# ==========================================
# 3. Main Execution Logic
# ==========================================

def run_backtests():
    config = BacktestConfig()
    registry = setup_registry()
    data_provider = OpenBBProvider() # Shared provider for single asset strategies

    total_results = []

    logger.info("=" * 60)
    logger.info(f"🚀 STARTING BACKTEST SESSION")
    logger.info(f"📅 Range: {config.start_date} to {config.end_date}")
    logger.info(f"💰 Capital: ${config.initial_cash:,.2f}")
    logger.info(f"📝 Strategies to Run: {list(config.active_strategies.keys())}")
    logger.info(f"🔢 Target Symbols: {config.target_symbols}")
    logger.info("=" * 60)

    for strat_name, presets in config.active_strategies.items():
        strat_info = registry.get(strat_name)
        
        if not strat_info:
            logger.warning(f"⚠️ Strategy '{strat_name}' not found in registry.")
            continue

        strat_class = strat_info["class"]
        available_presets = strat_info["presets"]
        strat_type = strat_info["type"]

        for preset_name in presets:
            if preset_name not in available_presets:
                logger.warning(f"⚠️ Preset '{preset_name}' not found for {strat_name}")
                continue

            logger.info(f"\n▶️ Running {strat_name} ({preset_name}) [Type: {strat_type.upper()}]")
            
            try:
                start_time = time.time()
                
                # -------------------------------------------------
                # BRANCH 1: Standard Single-Asset Strategies
                # -------------------------------------------------
                if strat_type == "single":
                    # Initialize Strategy
                    strategy_instance = strat_class(
                        data_provider=data_provider, 
                        **available_presets[preset_name]
                    )
                    
                    runner = BacktestRunner(
                        strategy=strategy_instance,
                        preset_name=preset_name,
                        symbols=config.target_symbols,
                        provider=data_provider,
                        interval="1d",
                        start_date=config.start_date,
                        end_date=config.end_date,
                        initial_cash=config.initial_cash
                    )
                    
                    # [FIX] Removed threading/fake progress bar logic
                    # The runner itself should handle progress logging
                    results = runner.run()

                    # Visualize
                    if config.save_charts:
                        prefix = f"{strat_name}_{preset_name}".lower()
                        runner.visualize(save=True, output_dir="charts", file_prefix=prefix)

                    # Collect Results for Final Summary
                    for symbol, report in results.items():
                        total_results.append({
                            "Strategy": strat_name,
                            "Preset": preset_name,
                            "Symbol": symbol,
                            "Final Value": f"${report['final_value']:,.2f}", # Added $
                            "Net Profit": f"${report['net_profit']:,.2f}",   # Added $
                            "Return": f"{report['return_pct']:.2f}%",      # [NEW] Added Return
                            "Win Rate": f"{report['win_rate']:.2f}%",        # Added %
                            "Trades": report["num_trades"],
                            "Max DD": f"{report['max_drawdown']:.2f}%"       # Added %
                        })

                # -------------------------------------------------
                # BRANCH 2: Portfolio Strategies (Sector Rotation)
                # -------------------------------------------------
                elif strat_type == "portfolio":
                    logger.info("⚡️ Delegating to Portfolio Runner...")
                    logger.info(f"  - Preset: {preset_name}")
                    logger.info(f"  - Rebalance Frequency: {'W-FRI' if preset_name == 'swing' else 'ME'}")
                    
                    # [MODIFIED] Capture the return value (metrics)
                    metrics = run_sector_rotation_backtest(
                        start_date=config.start_date,
                        end_date=config.end_date,
                        preset_name=preset_name,
                        rebalance_freq="W-FRI" if preset_name == "swing" else "M",
                        initial_capital=config.initial_cash
                    )
                    
                    # [MODIFIED] Populate table with real data
                    if metrics:
                        total_results.append({
                            "Strategy": strat_name,
                            "Preset": preset_name,
                            "Symbol": "PORTFOLIO (ETF)",
                            "Final Value": f"${metrics['final_value']:,.2f}", # Added $
                            "Net Profit": f"${metrics['net_profit']:,.2f}",   # Added $
                            "Return": f"{metrics['total_return']:.2f}%",    # [NEW] Added Return
                            "Win Rate": "N/A",
                            "Trades": "N/A",
                            "Max DD": f"{metrics['max_drawdown']:.2f}%"       # Added %
                        })
                    else:
                        logger.warning(f"No metrics returned for {strat_name}")

                duration = time.time() - start_time
                logger.info(f"✅ Completed {strat_name} in {duration:.2f}s")

            except Exception as e:
                logger.error(f"❌ Failed: {traceback.format_exc()}")

    # Print Final Summary Table
    if total_results:
        logger.info("\n🏆 FINAL BACKTEST SUMMARY 🏆")
        # Note: tabulate with headers='keys' will use the dictionary keys as headers
        logger.info(f"\n{tabulate(total_results, headers='keys', tablefmt='pretty')}")
    else:
        logger.warning("No results collected.")

if __name__ == "__main__":
    run_backtests()