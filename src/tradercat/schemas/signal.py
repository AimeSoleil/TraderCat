"""Signal schemas for API request/response."""
from datetime import datetime, date
from uuid import UUID
from pydantic import BaseModel, Field
from typing import Any


class SignalResponse(BaseModel):
    """Schema for signal response."""
    id: UUID
    run_date: date
    symbol: str
    strategy: str
    signal: str  # "buy", "sell", "hold", "rebalance"
    confidence: float
    reason: str | None
    ohlcv: dict[str, Any] | None
    indicators: dict[str, Any] | None
    scope: str  # "global" or "user"
    created_at: datetime

    model_config = {"from_attributes": True}


class SignalList(BaseModel):
    """Schema for signal list response."""
    signals: list[SignalResponse]
    total: int


class SignalQuery(BaseModel):
    """Schema for signal query filters."""
    run_date: date | None = None
    symbol: str | None = Field(None, max_length=20)
    strategy: str | None = Field(None, max_length=100)
    signal: str | None = Field(None, pattern="^(buy|sell|hold|rebalance)$")
    limit: int = Field(100, ge=1, le=1000)
    offset: int = Field(0, ge=0)
