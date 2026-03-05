"""Symbol/Watchlist schemas for API request/response."""
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field


class WatchlistItemBase(BaseModel):
    """Base watchlist item schema."""
    symbol: str = Field(..., min_length=1, max_length=20, pattern="^[A-Z0-9.]+$")
    description: str | None = Field(None, max_length=255)


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


class WatchlistBatchImportItem(BaseModel):
    """Single item in a batch import request."""
    symbol: str = Field(..., min_length=1, max_length=20, pattern="^[A-Z0-9.]+$")
    description: str | None = Field(None, max_length=255)


class WatchlistBatchImportRequest(BaseModel):
    """Schema for batch importing symbols to watchlist."""
    items: list[WatchlistBatchImportItem] = Field(..., min_length=1, max_length=200)


class WatchlistBatchImportResult(BaseModel):
    """Result for a single item in batch import."""
    symbol: str
    status: str  # "created", "exists", "error"
    detail: str | None = None


class WatchlistBatchImportResponse(BaseModel):
    """Schema for batch import response."""
    created: int
    skipped: int
    errors: int
    results: list[WatchlistBatchImportResult]


class WatchlistBatchRemoveRequest(BaseModel):
    """Schema for batch removing symbols from watchlist."""
    symbols: list[str] = Field(..., min_length=1, max_length=200)


class WatchlistBatchRemoveResult(BaseModel):
    """Result for a single item in batch remove."""
    symbol: str
    status: str  # "removed", "not_found"


class WatchlistBatchRemoveResponse(BaseModel):
    """Schema for batch remove response."""
    removed: int
    not_found: int
    results: list[WatchlistBatchRemoveResult]
