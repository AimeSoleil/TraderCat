from dataclasses import dataclass
from typing import Optional, List, Tuple, Union
from enum import Enum
import math

EPS = 1e-9

class Mode(Enum):
    BULL = "bull"
    BEAR = "bear"

    @classmethod
    def from_value(cls, v: Union["Mode", str]) -> "Mode":
        if isinstance(v, cls):
            return v
        if not isinstance(v, str):
            raise TypeError("mode must be Mode or str")
        vv = v.strip().lower()
        if vv in ("bull", "b"):
            return cls.BULL
        if vv in ("bear", "sell", "s"):
            return cls.BEAR
        raise ValueError("mode must be 'bull' or 'bear'")

@dataclass
class ScorerResult:
    """
    Single canonical confidence + reasons pair represent the final, mode-aware output.

    - conf: confidence for the mandated side (0..1)
    - reasons: list of reasons that contributed to conf (last line contains strength label)
    - signal: "buy" | "sell" | "hold"
    - strength_label: "强"/"中等"/"弱"/"观望"
    """
    conf: float
    reasons: List[str]
    signal: str
    strength_label: str

class SignalScorer:
    """
    Long-only or short-only scorer returning a single (conf, reasons) result.

    - mode: Mode or str ("bull"/"bear")
    - add(condition, reason, weight=1.0, strength=None) where strength is magnitude in [0..1]
    - evaluate() returns ScorerResult with combined conf/reasons
    """
    def __init__(self, mode: Union[Mode, str], threshold_percent: float = 0.6):
        self.mode = Mode.from_value(mode)
        self.threshold_percent = float(threshold_percent)
        self._entries: List[Tuple[str, float, float]] = []  # (reason, raw_weight, mag)
        self._raw_weights_sum: float = 0.0

    def add(self, condition: bool, reason: str, weight: float = 1.0, strength: Optional[float] = None):
        raw_w = float(weight or 0.0)
        if raw_w < 0.0:
            raw_w = 0.0
        self._raw_weights_sum += raw_w
        if not condition:
            return
        mag = 1.0 if strength is None else float(strength)
        if math.isnan(mag):
            mag = 0.0
        mag = max(0.0, min(1.0, mag))
        self._entries.append((reason, raw_w, mag))

    def _label(self, conf: float) -> str:
        if conf >= 0.9:
            return "强"
        if conf >= 0.75:
            return "中等"
        if conf >= self.threshold_percent:
            return "弱"
        return "观望"

    def evaluate(self) -> ScorerResult:
        raw_sum = max(self._raw_weights_sum, EPS)
        if not self._entries:
            label = "观望"
            return ScorerResult(conf=0.0, reasons=["无评分项", f"信号强度: {label} (0.000)"], signal="hold", strength_label=label)

        total = 0.0
        reasons: List[str] = []
        for reason, raw_w, mag in self._entries:
            eff = (raw_w / raw_sum) * mag
            if eff > EPS:
                total += eff
                reasons.append(reason)

        conf = round(min(1.0, total), 4)
        # decide signal using the mandated mode
        if conf >= self.threshold_percent:
            signal = "buy" if self.mode == Mode.BULL else "sell"
        else:
            signal = "hold"
        label = self._label(conf)

        # always append a strength line as the last reason for display
        if reasons:
            reasons = reasons + [f"信号强度: {label} ({conf:.3f})"]
        else:
            reasons = [f"信号强度: {label} ({conf:.3f})"]

        return ScorerResult(conf=float(conf), reasons=reasons, signal=signal, strength_label=label)

    def reset(self):
        self._entries = []
        self._raw_weights_sum = 0.0