from pydantic import BaseModel
from typing import Dict, Any

class SignalModel(BaseModel):
    strategy: str
    signal: str  # 'buy' | 'sell' | 'hold'
    details: Dict[str, Any] = {}