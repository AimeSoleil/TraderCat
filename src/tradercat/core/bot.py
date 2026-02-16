"""TraderBot - Core trading signal generation engine."""
import traceback
from typing import List, Optional, Dict, Any
from tradercat.core.data.openbb_provider import OpenBBProvider
from tradercat.logger.logger import get_logger
from tradercat.core.strategy.chart_pattern_strategy import ChartPatternStrategy, make_chart_pattern_presets
from tradercat.core.strategy.signal_model import SignalModel

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

logger = get_logger(__name__)

# ── Strategy class registry ───────────────────────────────────
STRATEGY_CLASS_MAP: Dict[str, type] = {
    "BollingerBreakoutStrategy": BollingerBreakoutStrategy,
    "BBandsReversalStrategy": BBandsReversalStrategy,
    "CandlestickReversalStrategy": CandlestickReversalStrategy,
    "ChartPatternStrategy": ChartPatternStrategy,
    "DivergenceStrategy": DivergenceStrategy,
    "FibonacciRetracementStrategy": FibonacciRetracementStrategy,
    "MomentumTrendStrategy": MomentumTrendStrategy,
}

# ── Hardcoded fallback defaults (when DB unavailable) ─────────
_FALLBACK_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "bbands_breakout": {
        "strategy_class": "BollingerBreakoutStrategy",
        "make_presets": make_bbands_breakout_presets,
        "default_preset": "gamma",
    },
    "bbands_reversal": {
        "strategy_class": "BBandsReversalStrategy",
        "make_presets": make_bbands_reversal_presets,
        "default_preset": "fade",
    },
    "candlestick_reversal": {
        "strategy_class": "CandlestickReversalStrategy",
        "make_presets": make_candlestick_reversal_presets,
        "default_preset": "gamma_dip",
    },
    "chart_pattern": {
        "strategy_class": "ChartPatternStrategy",
        "make_presets": make_chart_pattern_presets,
        "default_preset": "momentum_pattern",
    },
    "divergence": {
        "strategy_class": "DivergenceStrategy",
        "make_presets": make_divergence_presets,
        "default_preset": "trend_continuation",
    },
    "fibonacci_retracement": {
        "strategy_class": "FibonacciRetracementStrategy",
        "make_presets": make_fibonacci_presets,
        "default_preset": "trend_pullback",
    },
    "momentum": {
        "strategy_class": "MomentumTrendStrategy",
        "make_presets": make_momentum_presets,
        "default_preset": "swing_momentum",
    },
}


class StrategyFactory:
    """
    Centralized strategy initialization.

    Supports two modes:
      1. **DB-driven** (preferred) — receives ``strategy_configs`` loaded from
         the ``strategies`` + ``strategy_presets`` tables.
      2. **Fallback** — when ``strategy_configs`` is ``None`` or empty, uses
         hardcoded default presets so the pipeline can still run without a DB.
    """

    @staticmethod
    def get_single_asset_strategies(
        data_provider: OpenBBProvider,
        strategy_configs: Optional[List[Dict[str, Any]]] = None,
    ) -> List:
        """
        Build strategy instances from DB-loaded configs or hardcoded fallback.

        Args:
            data_provider: Data provider instance.
            strategy_configs: List of dicts with keys:
                ``name``, ``strategy_class``, ``parameters`` (from active preset).
                Only active strategies are included.
        """
        if strategy_configs:
            return StrategyFactory._from_db_configs(data_provider, strategy_configs)
        return StrategyFactory._from_fallback(data_provider)

    # ── DB-driven path ────────────────────────────────────────

    @staticmethod
    def _from_db_configs(
        data_provider: OpenBBProvider,
        configs: List[Dict[str, Any]],
    ) -> List:
        strategies = []
        for cfg in configs:
            cls_name = cfg["strategy_class"]
            cls = STRATEGY_CLASS_MAP.get(cls_name)
            if cls is None:
                logger.warning(f"Unknown strategy class '{cls_name}' — skipping")
                continue
            params = cfg.get("parameters") or {}
            try:
                strategies.append(cls(data_provider=data_provider, **params))
                logger.debug(f"Loaded strategy {cls_name} (preset params from DB)")
            except Exception as e:
                logger.error(f"Failed to instantiate {cls_name}: {e}")
        return strategies

    # ── Hardcoded fallback path ───────────────────────────────

    @staticmethod
    def _from_fallback(data_provider: OpenBBProvider) -> List:
        logger.warning("No DB strategy configs — using hardcoded fallback defaults")
        strategies = []
        for name, meta in _FALLBACK_DEFAULTS.items():
            cls = STRATEGY_CLASS_MAP[meta["strategy_class"]]
            presets = meta["make_presets"]()
            params = presets[meta["default_preset"]].copy()
            strategies.append(cls(data_provider=data_provider, **params))
        return strategies


class TraderBot:
    """
    Unified Trading Bot capable of running both Single-Asset and Portfolio strategies.
    Refactored for API service: removed executor dependency, now just returns signals.
    """

    def __init__(
        self,
        data_provider: Optional[OpenBBProvider] = None,
        strategy_configs: Optional[List[Dict[str, Any]]] = None,
    ):
        """
        Initialize TraderBot.
        
        Args:
            data_provider: Data provider instance
            strategy_configs: DB-loaded strategy+preset configs (from orchestrator).
                              Falls back to hardcoded defaults when ``None``.
        """
        self.data_provider = data_provider or OpenBBProvider()
        
        # Pre-load strategies (DB-driven or fallback)
        self.single_strategies = StrategyFactory.get_single_asset_strategies(
            self.data_provider,
            strategy_configs=strategy_configs,
        )

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
