from datetime import datetime
from pydantic import BaseModel
from typing import Dict, Any, Literal

class SignalModel(BaseModel):
    date: datetime
    symbol: str
    strategy: str
    signal: Literal["buy", "sell", "hold"]
    confidence: float = 0.0
    reason: str = "N/A"
    details: Dict[str, Any] = {}