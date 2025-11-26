from dataclasses import dataclass
from typing import List, Literal
from enum import Enum

from trade_bot.logger.logger import get_logger

logger = get_logger(__name__)

# ---------------- ENUM FOR FACTOR NAMES ----------------
class FactorName(Enum):
    # bb_bands_breakout_strategy
    BREAKOUT_TRIGGER = "breakout_trigger"
    SQUEEZE_CONFIRM = "squeeze_confirm"

    # bb_reversal_strategy
    BB_REVERSAL_CANDLE = "bb_reversal_candle"

    # candlestick_reversal_strategy
    REVERSAL_CANDLE = "reversal_candle"
    TREND_DIRECTION_CONFIRM = "trend_direction_confirm"

    # divergence_strategy
    DIVERGENCE = "divergence"

    # fibonacci_strategy
    FIB_ZONE_CONFIRM = "fib_zone_confirm"

    # momentum_strategy
    DAILY_TREND_CONFIRM = "daily_trend_confirm"
    HIGHER_TIMEFRAME_TREND_CONFIRM = "higher_timeframe_tend_confirm"

    # Common
    TREND_STRENGTH = "trend_strength"
    VOLUME_CONFIRM = "volume_confirm"
    EMA_ALIGNMENT = "ema_alignment"
    CONFLUENCE_BONUS = "confluence_bonus"
    MOMENTUM_CONFIRM = "momentum_confirm"


# ---------------- DATA CLASSES ----------------
@dataclass
class ScoringResult:
    score: float
    threshold: float
    signal: str
    reasons: List[str]

    def to_json(self) -> dict:
        return {
            "score": self.score,
            "threshold": self.threshold,
            "signal": self.signal,
            "reasons": self.reasons,
        }

    def pretty_print(self):
        logger.info(f"Score: {self.score}, Threshold: {self.threshold}, Signal: {self.signal}")
        logger.info("Reasons:")
        for r in self.reasons:
            logger.info(f" - {r}")


@dataclass
class Factor:
    name: FactorName
    description: str
    weight: float
    condition: bool

    def effective_weight(self, vol_spike: bool, atr_high: bool) -> float:
        adaptive_weight = self.weight
        if vol_spike and self.name == FactorName.VOLUME_CONFIRM:
            adaptive_weight += 0.05
        if atr_high and self.name == FactorName.VOLATILITY_FILTER:
            adaptive_weight += 0.05
        return adaptive_weight

# ---------------- SCORING ENGINE ----------------
class ScoringEngine:
    def __init__(
        self,
        required_factors: List[FactorName],
        determined_factors: List[FactorName] = None,
        base_threshold: float = 0.7,
        atr_volatility_factor: float = 0.15,
    ):
        self.base_threshold = base_threshold
        self.atr_volatility_factor = atr_volatility_factor
        self.required_factors = required_factors
        self.determined_factors = determined_factors

    # def dynamic_threshold(self, atr: float, avg_atr: float) -> float:
    #     if atr > avg_atr * 1.2:
    #         return min(1.0, self.base_threshold + self.atr_volatility_factor)
    #     return self.base_threshold

    def _validate_factors(self, factors: List[Factor]) -> List[str]:
        if not self.required_scoring_factors:
            raise ValueError("Missing required scoring factors definition")

        existing_names = {f.name for f in factors}
        missing = [
            name.value
            for name in self.required_factors
            if name not in existing_names
        ]
        if missing:
            raise ValueError(f"Missing factors: {missing}")

    def compute_score(
        self, 
        factors: List[Factor], 
        side: Literal["long", "short", "hold"]
    ) -> ScoringResult:
        # Validate
        self._validate_factors(factors)

        # Scoring Logic
        score = 0.0
        reasons = []

        for factor in factors:
            if factor.condition:
                reasons.append(f"{factor.name.value} (+{score:.2f}) {factor.description}")

        score = min(1.0, score)
        signal = "hold"
        if side != "hold":
            if score >= self.base_threshold:
                if self.determined_factors:
                    filtered_factors = [f for f in factors if f.name in self.determined_factors]
                    if all(f.condition for f in filtered_factors):
                        if side == "long":
                            signal = "buy"
                        else:
                            signal = "sell"
                else:
                    if side == "long":
                        signal = "buy"
                    else:
                        signal = "sell"
            else:
                reasons.append(f'scoring ({score}) not exceeds threshold ({self.base_threshold})')
        else:
            reasons.appends(f'side is {side}')

        return ScoringResult(
            score=round(score, 3), threshold=self.base_threshold, signal=signal, reasons=reasons
        )
