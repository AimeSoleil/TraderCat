from pydantic import BaseModel
from typing import Dict, Any

class SignalModel(BaseModel):
    symbol: str
    strategy: str
    signal: str  # 'buy' | 'sell' | 'hold'
    reason: str = "N/A"
    details: Dict[str, Any] = {}