import traceback
from typing import List, Optional
from tradercat.data.openbb_provider import OpenBBProvider
from tradercat.logger.logger import get_logger
from tradercat.strategy.chart_pattern_strategy import ChartPatternStrategy, make_chart_pattern_presets
from tradercat.strategy.signal_model import SignalModel
from tradercat.strategy.strategy_presets import StrategyPreset

# Import Strategies and Presets
from tradercat.strategy.bbands_breakout_strategy import (
    BollingerBreakoutStrategy,
    make_bbands_breakout_presets,
)
from tradercat.strategy.bbands_reversal_strategy import (
    BBandsReversalStrategy,
    make_bbands_reversal_presets,
)
from tradercat.strategy.candlestick_reversal_strategy import (
    CandlestickReversalStrategy,
    make_candlestick_reversal_presets,
)
from tradercat.strategy.divergence_strategy import (
    DivergenceStrategy,
    make_divergence_presets,
)
from tradercat.strategy.fibonacci_retracement_strategy import (
    FibonacciRetracementStrategy,
    make_fibonacci_presets,
)
from tradercat.strategy.momentum_strategy import (
    MomentumTrendStrategy,
    make_momentum_presets,
)
from tradercat.strategy.sector_rotation_strategy import SectorRotationStrategy, make_sector_rotation_presets

logger = get_logger(__name__)

class StrategyFactory:
    """
    Centralized place to initialize strategies. 
    Easier to manage configurations and presets here.
    """
    @staticmethod
    def get_single_asset_strategies(data_provider: OpenBBProvider) -> List:
        # Explicitly name 'data_provider' to avoid collision with positional args
        # if the strategy class definition changed.
        return [
            BollingerBreakoutStrategy(data_provider=data_provider, **make_bbands_breakout_presets()["gamma"]),
            BBandsReversalStrategy(data_provider=data_provider, **make_bbands_reversal_presets()["fade"]),
            CandlestickReversalStrategy(data_provider=data_provider, **make_candlestick_reversal_presets()["gamma_dip"]),
            ChartPatternStrategy(data_provider=data_provider, **make_chart_pattern_presets()["momentum_pattern"]),
            DivergenceStrategy(data_provider=data_provider, **make_divergence_presets()["trend_continuation"]),
            FibonacciRetracementStrategy(data_provider=data_provider, **make_fibonacci_presets()["trend_pullback"]),
            MomentumTrendStrategy(data_provider=data_provider, **make_momentum_presets()["swing_momentum"]),
        ]

    @staticmethod
    def get_portfolio_strategies(data_provider: OpenBBProvider, preset: StrategyPreset = "swing") -> List:
        # Note: make_sector_rotation_presets() now accepts preset_name directly
        return [
            SectorRotationStrategy(data_provider=data_provider, **make_sector_rotation_presets()[preset]),
        ]


class TraderBot:
    """
    Unified Trading Bot capable of running both Single-Asset and Portfolio strategies.
    """

    def __init__(self, executor, data_provider: Optional[OpenBBProvider] = None):
        self.executor = executor
        self.data_provider = data_provider or OpenBBProvider()
        
        # Pre-load strategies
        self.single_strategies = StrategyFactory.get_single_asset_strategies(self.data_provider)
        self.portfolio_strategies = StrategyFactory.get_portfolio_strategies(self.data_provider)

    async def process_symbol(self, symbol: str) -> List[SignalModel]:
        """
        Runs all single-asset strategies for a specific symbol.
        """
        logger.info(f"🤖 Processing symbol: {symbol}...")

        # 1. Determine Data Requirements
        # Calculate the max lookback needed across all strategies to fetch data efficiently once
        max_lookback = max(s.get_lookback_window() for s in self.single_strategies) if self.single_strategies else 30
        
        # 2. Fetch Data
        candles = self.data_provider.get_price_data(symbol, interval="1d", lookback=max_lookback)
        
        if not candles:
            logger.warning(f"⚠️ No candle data found for {symbol}")
            return []

        logger.info(f"Fetched {len(candles)} candles for {symbol}")

        # 3. Generate Signals
        signals = []
        for strategy in self.single_strategies:
            try:
                # Pass only the required window to the strategy
                strategy_lookback = strategy.get_lookback_window()
                signal = strategy.generate_signal(symbol, candles=candles[-strategy_lookback:])
                logger.info(f"Strategy {strategy.__class__.__name__} generated signal: {signal.signal} for {symbol}")
                signals.append(signal)
            except Exception as e:
                logger.error(f"Error running {strategy.__class__.__name__} on {symbol}: {traceback.format_exc()}")

        # 4. Aggregate & Execute
        final_signals = self._aggregate_signals(signals)
        
        if final_signals:
            self.executor.execute_trade(final_signals, symbol)
        
        return final_signals

    async def process_portfolio(self) -> List[SignalModel]:
        """
        Runs global/portfolio strategies (e.g., Sector Rotation).
        """
        logger.info("🌍 Processing Portfolio Strategies...")
        
        signals = []
        for strategy in self.portfolio_strategies:
            try:
                # Portfolio strategies usually fetch their own universe data internally
                signal = strategy.generate_signal()
                signals.append(signal)
            except Exception as e:
                logger.error(f"Error running {strategy.__class__.__name__}: {traceback.format_exc()}")

        final_signals = self._aggregate_signals(signals)
        
        # Executor needs to handle 'None' symbol or specific portfolio logic
        if final_signals:
            self.executor.execute_trade(final_signals, symbol="PORTFOLIO")

        return final_signals

    def _aggregate_signals(self, signals: List[SignalModel]) -> List[SignalModel]:
        """
        Filter or combine signals. 
        Currently returns all valid signals, but can be extended for voting logic.
        """
        # valid_signals = [s for s in signals if s and s.signal != "hold"]
        # return valid_signals

        return signals
