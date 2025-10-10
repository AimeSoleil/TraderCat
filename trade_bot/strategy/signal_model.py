from datetime import datetime
from pydantic import BaseModel
from typing import Dict, Any

class SignalModel(BaseModel):
    date: datetime
    symbol: str
    strategy: str
    signal: str  # 'buy' | 'sell' | 'hold'
    confidence: float = 0.0
    reason: str = "N/A"
    details: Dict[str, Any] = {}