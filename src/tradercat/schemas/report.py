"""Report schemas for API request/response."""
from datetime import datetime, date
from uuid import UUID
from pydantic import BaseModel, Field
from typing import Any


class ReportResponse(BaseModel):
    """Schema for report response."""
    id: UUID
    user_id: UUID
    run_date: date
    symbol: str
    report_type: str
    content_md: str
    model_used: str | None
    persona_used: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ReportDetail(ReportResponse):
    """Schema for detailed report response (includes input context)."""
    input_context: dict[str, Any] | None

    model_config = {"from_attributes": True}


class ReportList(BaseModel):
    """Schema for report list response."""
    reports: list[ReportResponse]
    total: int


class ReportQuery(BaseModel):
    """Schema for report query filters."""
    run_date: date | None = None
    symbol: str | None = Field(None, max_length=20)
    report_type: str | None = Field(None, max_length=50)
    limit: int = Field(100, ge=1, le=1000)
    offset: int = Field(0, ge=0)
