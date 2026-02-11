"""Strategy schemas for API request/response."""
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field
from typing import Any


class StrategyInfo(BaseModel):
    """Schema for strategy information."""
    name: str
    description: str
    default_preset: str
    default_parameters: dict[str, Any]


class StrategyConfigResponse(BaseModel):
    """Schema for user's strategy configuration."""
    id: UUID
    strategy_name: str
    preset_name: str | None
    parameters: dict[str, Any] | None
    is_active: bool
    updated_at: datetime

    model_config = {"from_attributes": True}


class StrategyWithUserConfig(StrategyInfo):
    """Schema combining strategy info with user overrides."""
    user_config: StrategyConfigResponse | None = None


class StrategyConfigUpdate(BaseModel):
    """Schema for updating strategy configuration."""
    preset_name: str | None = Field(None, max_length=100)
    parameters: dict[str, Any] | None = None
    is_active: bool | None = None


class StrategyListResponse(BaseModel):
    """Schema for strategy list response."""
    strategies: list[StrategyWithUserConfig]
    total: int
