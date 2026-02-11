"""TraderBot - Core trading signal generation engine."""
import traceback
from typing import List, Optional, Dict, Any
from tradercat.core.data.openbb_provider import OpenBBProvider
from tradercat.logger.logger import get_logger
from tradercat.core.strategy.chart_pattern_strategy import ChartPatternStrategy, make_chart_pattern_presets
from tradercat.core.strategy.signal_model import SignalModel
from tradercat.core.strategy.strategy_presets import StrategyPreset

# Import Strategies and Presets
from tradercat.core.strategy.bbands_breakout_strategy import (
    BollingerBreakoutStrategy,
    make_bbands_breakout_presets,
)
from tradercat.core.strategy.bbands_reversal_strategy import (
    BBandsReversalStrategy,
    make_bbands_reversal_presets,
)
from tradercat.core.strategy.candlestick_reversal_strategy import (
    CandlestickReversalStrategy,
    make_candlestick_reversal_presets,
)
from tradercat.core.strategy.divergence_strategy import (
    DivergenceStrategy,
    make_divergence_presets,
)
from tradercat.core.strategy.fibonacci_retracement_strategy import (
    FibonacciRetracementStrategy,
    make_fibonacci_presets,
)
from tradercat.core.strategy.momentum_strategy import (
    MomentumTrendStrategy,
    make_momentum_presets,
)
from tradercat.core.strategy.sector_rotation_strategy import SectorRotationStrategy, make_sector_rotation_presets

logger = get_logger(__name__)


class StrategyFactory:
    """
    Centralized place to initialize strategies.
    Easier to manage configurations and presets here.
    """
    @staticmethod
    def get_single_asset_strategies(
        data_provider: OpenBBProvider,
        user_overrides: Optional[Dict[str, Dict[str, Any]]] = None
    ) -> List:
        """
        Get single-asset strategies with optional user parameter overrides.
        
        Args:
            data_provider: Data provider instance
            user_overrides: Dict mapping strategy names to parameter overrides
        """
        user_overrides = user_overrides or {}
        
        # Default presets for each strategy
        strategies = []
        
        # BBands Breakout
        params = make_bbands_breakout_presets()["gamma"].copy()
        if "bbands_breakout" in user_overrides:
            params.update(user_overrides["bbands_breakout"])
        strategies.append(BollingerBreakoutStrategy(data_provider=data_provider, **params))
        
        # BBands Reversal
        params = make_bbands_reversal_presets()["fade"].copy()
        if "bbands_reversal" in user_overrides:
            params.update(user_overrides["bbands_reversal"])
        strategies.append(BBandsReversalStrategy(data_provider=data_provider, **params))
        
        # Candlestick Reversal
        params = make_candlestick_reversal_presets()["gamma_dip"].copy()
        if "candlestick_reversal" in user_overrides:
            params.update(user_overrides["candlestick_reversal"])
        strategies.append(CandlestickReversalStrategy(data_provider=data_provider, **params))
        
        # Chart Pattern
        params = make_chart_pattern_presets()["momentum_pattern"].copy()
        if "chart_pattern" in user_overrides:
            params.update(user_overrides["chart_pattern"])
        strategies.append(ChartPatternStrategy(data_provider=data_provider, **params))
        
        # Divergence
        params = make_divergence_presets()["trend_continuation"].copy()
        if "divergence" in user_overrides:
            params.update(user_overrides["divergence"])
        strategies.append(DivergenceStrategy(data_provider=data_provider, **params))
        
        # Fibonacci
        params = make_fibonacci_presets()["trend_pullback"].copy()
        if "fibonacci_retracement" in user_overrides:
            params.update(user_overrides["fibonacci_retracement"])
        strategies.append(FibonacciRetracementStrategy(data_provider=data_provider, **params))
        
        # Momentum
        params = make_momentum_presets()["swing_momentum"].copy()
        if "momentum" in user_overrides:
            params.update(user_overrides["momentum"])
        strategies.append(MomentumTrendStrategy(data_provider=data_provider, **params))
        
        return strategies

    @staticmethod
    def get_portfolio_strategies(
        data_provider: OpenBBProvider,
        preset: StrategyPreset = "swing",
        user_overrides: Optional[Dict[str, Any]] = None
    ) -> List:
        """
        Get portfolio strategies with optional user parameter overrides.
        """
        user_overrides = user_overrides or {}
        params = make_sector_rotation_presets()[preset].copy()
        params.update(user_overrides)
        return [
            SectorRotationStrategy(data_provider=data_provider, **params),
        ]


class TraderBot:
    """
    Unified Trading Bot capable of running both Single-Asset and Portfolio strategies.
    Refactored for API service: removed executor dependency, now just returns signals.
    """

    def __init__(
        self,
        data_provider: Optional[OpenBBProvider] = None,
        user_strategy_overrides: Optional[Dict[str, Dict[str, Any]]] = None
    ):
        """
        Initialize TraderBot.
        
        Args:
            data_provider: Data provider instance
            user_strategy_overrides: User-specific strategy parameter overrides
        """
        self.data_provider = data_provider or OpenBBProvider()
        self.user_strategy_overrides = user_strategy_overrides or {}
        
        # Pre-load strategies with user overrides
        self.single_strategies = StrategyFactory.get_single_asset_strategies(
            self.data_provider, 
            self.user_strategy_overrides
        )
        self.portfolio_strategies = StrategyFactory.get_portfolio_strategies(self.data_provider)

    async def process_symbol(self, symbol: str) -> List[SignalModel]:
        """
        Runs all single-asset strategies for a specific symbol.
        Returns list of generated signals (no execution).
        """
        logger.info(f"🤖 Processing symbol: {symbol}...")

        # 1. Determine Data Requirements
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
                strategy_lookback = strategy.get_lookback_window()
                signal = strategy.generate_signal(symbol, candles=candles[-strategy_lookback:])
                logger.info(f"Strategy {strategy.__class__.__name__} generated signal: {signal.signal} for {symbol}")
                signals.append(signal)
            except Exception as e:
                logger.error(f"Error running {strategy.__class__.__name__} on {symbol}: {traceback.format_exc()}")

        return signals

    async def process_portfolio(self) -> List[SignalModel]:
        """
        Runs global/portfolio strategies (e.g., Sector Rotation).
        Returns list of generated signals (no execution).
        """
        logger.info("🌍 Processing Portfolio Strategies...")
        
        signals = []
        for strategy in self.portfolio_strategies:
            try:
                signal = strategy.generate_signal()
                signals.append(signal)
            except Exception as e:
                logger.error(f"Error running {strategy.__class__.__name__}: {traceback.format_exc()}")

        return signals
