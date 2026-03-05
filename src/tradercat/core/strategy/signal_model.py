from datetime import datetime
from pydantic import BaseModel
from typing import Dict, Any, Literal

class SignalModel(BaseModel):
    date: datetime | None
    symbol: str
    strategy: str
    signal: Literal["buy", "sell", "hold", "rebalance"]
    confidence: float = 0.0
    reason: str = "N/A"
    ohlcv: Dict[str, Any] = {}
    indicators: Dict[str, Any] = {}