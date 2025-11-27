from dataclasses import dataclass
from typing import List, Literal
from enum import Enum

from trade_bot.logger.logger import get_logger

logger = get_logger(__name__)

EPS = 1e-9

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
    MOMENTUM_CONFIRM = "momentum_confirm"
    CONFLUENCE_BONUS = "confluence_bonus"


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

# ---------------- SCORING ENGINE ----------------
class ScoringEngine:
    def __init__(
        self,
        required_factors: List[FactorName],
        determined_factors: List[FactorName] = None,
        base_threshold: float = 0.7,
        is_volatility_ok: bool = False,
    ):
        self.base_threshold = base_threshold
        self.required_factors = required_factors
        self.determined_factors = determined_factors or []
        self.is_volatility_ok = is_volatility_ok

    def _validate_factors(self, factors: List[Factor]) -> List[str]:
        if not self.required_factors:
            raise ValueError("Missing required scoring factors definition")

        existing_names = {f.name for f in factors}
        missing = [
            name.value
            for name in self.required_factors
            if name not in existing_names
        ]
        if missing:
            raise ValueError(f"Missing factors: {missing}")
    
    def _adaptive_threshold(self) -> float:
        # increase threshold in high volatility
        return self.base_threshold + (0.05 if self.is_volatility_ok else 0.0)

    def compute_score(
        self, 
        factors: List[Factor], 
        side: Literal["long", "short", "hold"]
    ) -> ScoringResult:
        # Validate
        self._validate_factors(factors)

        # Scoring Logic
        # Normalize weights
        total_weight = sum(f.weight for f in factors)
        normalized_score = 0.0
        reasons = []

        for factor in factors:
            if factor.condition:
                contribution = factor.weight / (total_weight if total_weight > EPS else 1.0)
                normalized_score += contribution
                reasons.append(f"{factor.description} (+{contribution:.2f})")

        # Determine signal
        normalized_score = min(1.0, normalized_score)
        threshold = self._adaptive_threshold()
        signal = "hold"
        if side != "hold":
            if normalized_score >= threshold:
                if self.determined_factors:
                    filtered = [f for f in factors if f.name in self.determined_factors]
                    if all(f.condition for f in filtered):
                        signal = "buy" if side == "long" else "sell"
                    else:
                        reasons.append("关键确认因子未全部满足")
                else:
                    signal = "buy" if side == "long" else "sell"
            else:
                reasons.append(f"得分 ({normalized_score:.2f}) 未超过阈值 ({threshold:.2f})")
        else:
            reasons.append("hold - 暂时没有明确的方向")

        return ScoringResult(
            score=round(normalized_score, 3),
            threshold=threshold,
            signal=signal,
            reasons=reasons
        )
