from dataclasses import dataclass
from typing import List, Literal, Optional
from enum import Enum

from tradercat.logger.logger import get_logger

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

    # chart_pattern_strategy
    CHART_PATTERN_DETECTED = "chart_pattern_detected"

    # divergence_strategy
    DIVERGENCE = "divergence"

    # fibonacci_strategy
    FIB_ZONE_CONFIRM = "fib_zone_confirm"

    # momentum_strategy
    DAILY_TREND_CONFIRM = "daily_trend_confirm"
    HIGHER_TIMEFRAME_TREND_CONFIRM = "higher_timeframe_tend_confirm"

    # Common
    TREND_STRENGTH = "trend_strength"
    VOLATILITY_HEALTH = "volatility_health"
    VOLUME_CONFIRM = "volume_confirm"
    EMA_ALIGNMENT = "ema_alignment"
    MOMENTUM_CONFIRM = "momentum_confirm"
    CONFLUENCE_BONUS = "confluence_bonus"
    VOLATILITY_OK = "volatility_ok"  # Gatekeeper factor


# ---------------- DATA CLASSES ----------------
@dataclass
class ScoringResult:
    score: float
    threshold: float
    signal: Literal["buy", "sell", "hold"]
    reasons: List[str]

    def to_json(self) -> dict:
        return {
            "score": self.score,
            "threshold": self.threshold,
            "signal": self.signal,
            "reasons": self.reasons,
        }

    def pretty_print(self):
        logger.info(f"Signal: {self.signal.upper()} | Score: {self.score:.2f}/{self.threshold:.2f}")
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
        base_threshold: float = 0.7,
        required_factors: Optional[List[FactorName]] = None,
        determined_factors: Optional[List[FactorName]] = None,
        is_volatility_ok: bool = True,
        volatility_penalty: float = 0.05,  # <--- [NEW] Default reduced to 5%, configurable
    ):
        """
        :param base_threshold: logic threshold to trigger a trade (e.g. 0.7)
        :param required_factors: List of factors that MUST be present in the calculation input (for validation).
        :param determined_factors: List of factors that MUST be TRUE. If any is False, score becomes 0 (Veto).
        :param is_volatility_ok: Market regime flag. If False, threshold increases to reduce risk.
        :param volatility_penalty: Amount to increase threshold by if is_volatility_ok is False.
        """
        self.base_threshold = base_threshold
        self.required_factors = required_factors or []
        self.determined_factors = determined_factors or []
        self.is_volatility_ok = is_volatility_ok
        self.vol_penalty = volatility_penalty # Store it

    def _validate_factors(self, factors: List[Factor]) -> None:
        if not self.required_factors:
            return

        existing_names = {f.name for f in factors}
        missing = [
            name.value
            for name in self.required_factors
            if name not in existing_names
        ]
        if missing:
            raise ValueError(f"Scoring Engine Configuration Error: Missing factors {missing}")

    def _adaptive_threshold(self) -> float:
        # LOGIC:
        # If volatility is OK, use base threshold.
        # If NOT OK, penalize by configurable amount.
        if not self.is_volatility_ok:
            return min(1.0, self.base_threshold + self.vol_penalty)
        return self.base_threshold

    def _trading_signal(self, side: Literal["long", "short", "neutral"]) -> Literal["buy", "sell", "hold"]:
        if side == "neutral":
            return "hold"
        return "buy" if side == "long" else "sell"

    def compute_score(
        self, 
        factors: List[Factor], 
        side: Literal["long", "short", "neutral"]
    ) -> ScoringResult:
        
        # 1. Validation
        self._validate_factors(factors)

        # 2. Calculate Normalized Score First (So we keep the score even if Vetoed)
        total_weight = sum(f.weight for f in factors)
        if total_weight < EPS:
            logger.warning("Total factor weight is near zero. Check configuration.")
            return ScoringResult(0.0, self.base_threshold, "hold", ["Configuration Error: Zero Weight"])

        normalized_score = 0.0
        reasons = []
        
        # Keep track of factor conditions to check Veto later
        factor_conditions = {}

        for factor in factors:
            factor_conditions[factor.name] = factor.condition
            contrib = (factor.weight / total_weight)
            
            if factor.condition:
                normalized_score += contrib
                reasons.append(f"[✓] {factor.description} (+{contrib:.2f})")
            else:
                reasons.append(f"[x] {factor.description} (Missed)")

        # Cap score at 1.0 (float robustness)
        normalized_score = min(1.0, normalized_score)

        # 3. Veto Check (Critical Factors)
        # Logic: We calculate score first, THEN check veto. 
        # If veto triggers, signal is forced to HOLD, but score remains visible for debugging.
        veto_triggered = False
        
        if self.determined_factors:
            for mandatory_name in self.determined_factors:
                # If the mandatory factor exists AND is False -> VETO
                if mandatory_name in factor_conditions and not factor_conditions[mandatory_name]:
                    veto_triggered = True
                    # Insert warning at the very top of reasons list
                    reasons.insert(0, f"[!] VETO: Critical factor '{mandatory_name.value}' not met.")

        # 4. Determine Threshold
        threshold = self._adaptive_threshold()
        if not self.is_volatility_ok:
            reasons.append("(!) Volatility Penalty Applied (+0.15 to threshold)")

        # 5. Final Decision Logic
        final_signal = "hold"
        is_score_passing = normalized_score >= threshold

        if veto_triggered:
            # FORCE HOLD due to Veto, regardless of how high the score is
            final_signal = "hold"
        elif is_score_passing:
            if side == "neutral":
                # High Score + Neutral Side = High Quality Setup emerging
                final_signal = "hold"
                reasons.append("High Score (Setup Quality Good), waiting for Trigger/Direction")
            else:
                # High Score + Direction = TRADE
                final_signal = self._trading_signal(side)
        else:
            final_signal = "hold"
            reasons.append(f"Score ({normalized_score:.2f}) < Threshold ({threshold:.2f})")

        return ScoringResult(
            score=round(normalized_score, 3), # Return the calced score even if vetoed
            threshold=round(threshold, 3),
            signal=final_signal,
            reasons=reasons
        )
