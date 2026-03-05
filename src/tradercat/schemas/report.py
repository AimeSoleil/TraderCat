"""Report schemas for API request/response.

Pipeline v2 tables:
  - macro_regime_contexts  → MacroRegimeContextResponse / Detail / List
  - symbol_execution_plans → SymbolExecutionPlanResponse / Detail / List
  - user_briefings         → UserBriefingResponse / Detail / List
"""
from datetime import datetime, date
from uuid import UUID
from pydantic import BaseModel, Field
from typing import Any


# --- Macro Regime Context Schemas ---

class MacroRegimeContextResponse(BaseModel):
    """Schema for macro regime context list item."""
    id: UUID
    run_date: date
    regime_label: str | None
    regime_score: float | None
    content_md: str
    model_used: str | None
    identity_used: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class MacroRegimeContextDetail(MacroRegimeContextResponse):
    """Schema with full details including downstream_filters and input_context."""
    downstream_filters: dict[str, Any] | None
    input_context: dict[str, Any] | None

    model_config = {"from_attributes": True}


class MacroRegimeContextList(BaseModel):
    """Schema for macro regime context list response."""
    reports: list[MacroRegimeContextResponse]
    total: int


# --- Symbol Execution Plan Schemas ---

class SymbolExecutionPlanResponse(BaseModel):
    """Schema for symbol execution plan list item."""
    id: UUID
    run_date: date
    symbol: str
    structure: str | None
    direction: str | None
    thesis: str | None
    content_md: str | None
    model_used: str | None
    identity_used: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class SymbolExecutionPlanDetail(SymbolExecutionPlanResponse):
    """Schema with full execution plan details."""
    rationale: str | None
    legs: list[dict[str, Any]] | None
    entry_trigger: str | None
    stop_loss: str | None
    profit_target: str | None
    time_stop: str | None
    max_loss: str | None
    max_profit: str | None
    breakeven: str | None
    rr_ratio: str | None
    allocation: str | None
    dte: int | None
    raw_json: dict[str, Any] | None

    model_config = {"from_attributes": True}


class SymbolExecutionPlanList(BaseModel):
    """Schema for symbol execution plan list response."""
    reports: list[SymbolExecutionPlanResponse]
    total: int


# --- User Briefing Schemas ---

class UserBriefingResponse(BaseModel):
    """Schema for user briefing list item."""
    id: UUID
    user_id: UUID
    run_date: date
    content_md: str
    model_used: str | None
    identity_used: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class UserBriefingDetail(UserBriefingResponse):
    """Schema with full details including input_context."""
    input_context: dict[str, Any] | None

    model_config = {"from_attributes": True}


class UserBriefingList(BaseModel):
    """Schema for user briefing list response."""
    reports: list[UserBriefingResponse]
    total: int
