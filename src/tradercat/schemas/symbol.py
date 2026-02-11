"""Symbol/Watchlist schemas for API request/response."""
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field


class WatchlistItemBase(BaseModel):
    """Base watchlist item schema."""
    symbol: str = Field(..., min_length=1, max_length=20, pattern="^[A-Z0-9.]+$")
    company_name: str | None = Field(None, max_length=255)


class WatchlistItemCreate(WatchlistItemBase):
    """Schema for adding a symbol to watchlist."""
    pass


class WatchlistItemResponse(WatchlistItemBase):
    """Schema for watchlist item response."""
    id: UUID
    user_id: UUID
    added_at: datetime

    model_config = {"from_attributes": True}


class WatchlistItemList(BaseModel):
    """Schema for watchlist list response."""
    items: list[WatchlistItemResponse]
    total: int
