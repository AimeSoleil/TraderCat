"""Report schemas for API request/response."""
from datetime import datetime, date
from uuid import UUID
from pydantic import BaseModel, Field
from typing import Any


# --- Global Report Schemas ---

class GlobalReportResponse(BaseModel):
    """Schema for global report response."""
    id: UUID
    run_date: date
    symbol: str | None
    report_type: str
    content_md: str
    model_used: str | None
    identity_used: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class GlobalReportDetail(GlobalReportResponse):
    """Schema for detailed global report response (includes input context)."""
    input_context: dict[str, Any] | None

    model_config = {"from_attributes": True}


class GlobalReportList(BaseModel):
    """Schema for global report list response."""
    reports: list[GlobalReportResponse]
    total: int


# --- User Report Schemas ---

class UserReportResponse(BaseModel):
    """Schema for user report response."""
    id: UUID
    user_id: UUID
    run_date: date
    report_type: str
    content_md: str
    model_used: str | None
    identity_used: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class UserReportDetail(UserReportResponse):
    """Schema for detailed user report response (includes input context)."""
    input_context: dict[str, Any] | None

    model_config = {"from_attributes": True}


class UserReportList(BaseModel):
    """Schema for user report list response."""
    reports: list[UserReportResponse]
    total: int
