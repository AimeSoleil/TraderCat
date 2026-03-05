"""Pydantic schemas for LLM token management."""
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field


class LlmTokenCreate(BaseModel):
    """Schema for creating an LLM token."""

    provider_name: str = Field(..., max_length=100, description="LLM provider name, e.g. openai, anthropic, gemini, github")
    token: str = Field(..., max_length=500, description="API key / token value")
    description: Optional[str] = Field(None, max_length=500, description="Human-readable description")
    is_active: bool = Field(False, description="Set as the active token (deactivates others)")


class LlmTokenUpdate(BaseModel):
    """Schema for updating an LLM token."""

    description: Optional[str] = Field(None, max_length=500)
    is_active: Optional[bool] = None


class LlmTokenResponse(BaseModel):
    """Schema for LLM token response — token is masked."""

    id: str
    provider_name: str
    token_preview: str = Field(..., description="Masked token, e.g. sk-****abcd")
    description: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class LlmTokenListResponse(BaseModel):
    """Wrapper for list of LLM tokens."""

    items: List[LlmTokenResponse]
    total: int
