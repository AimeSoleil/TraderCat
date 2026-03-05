"""Strategy and StrategyPreset schemas for API request/response."""
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field
from typing import Any


# ── StrategyPreset Schemas ──

class StrategyPresetCreate(BaseModel):
    """Create a new preset for a strategy."""
    name: str = Field(..., max_length=100)
    description: str | None = Field(None, max_length=500)
    parameters: dict[str, Any]


class StrategyPresetUpdate(BaseModel):
    """Update an existing preset (partial)."""
    description: str | None = Field(None, max_length=500)
    parameters: dict[str, Any] | None = None


class StrategyPresetResponse(BaseModel):
    """Preset response."""
    id: UUID
    strategy_id: UUID
    name: str
    description: str | None
    parameters: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class StrategyPresetBatchUpdate(BaseModel):
    """Batch update presets for a strategy."""
    presets: list[StrategyPresetCreate]


# ── Strategy Schemas ──

class StrategyResponse(BaseModel):
    """Strategy response with active preset info."""
    id: UUID
    name: str
    description: str | None
    strategy_class: str
    default_preset_name: str
    active_preset_id: UUID | None
    active_preset: StrategyPresetResponse | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class StrategyWithPresets(StrategyResponse):
    """Strategy response including all presets."""
    presets: list[StrategyPresetResponse] = []


class StrategyActivePresetUpdate(BaseModel):
    """Update which preset is active for a strategy."""
    active_preset_id: UUID | None = None


class StrategyListResponse(BaseModel):
    """Strategy list wrapper."""
    strategies: list[StrategyResponse]
    total: int


class StrategyPresetListResponse(BaseModel):
    """Preset list wrapper."""
    presets: list[StrategyPresetResponse]
    total: int
