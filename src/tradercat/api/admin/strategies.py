"""Strategy management API endpoints (Admin only).

Manages global Strategy and StrategyPreset records.
Strategies are NOT user-bound — they are shared pipeline configuration.
"""
from uuid import UUID
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from tradercat.api.deps import CurrentAdminUser, DatabaseSession
from tradercat.models import Strategy, StrategyPreset
from tradercat.schemas.strategy import (
    StrategyResponse,
    StrategyWithPresets,
    StrategyListResponse,
    StrategyActivePresetUpdate,
    StrategyPresetResponse,
    StrategyPresetCreate,
    StrategyPresetUpdate,
    StrategyPresetBatchUpdate,
    StrategyPresetListResponse,
)

router = APIRouter(prefix="/strategies", tags=["admin-strategies"])


# ─── Strategy endpoints ──────────────────────────────────────────

@router.get("", response_model=StrategyListResponse)
async def list_strategies(
    db: DatabaseSession,
    _admin: CurrentAdminUser,
):
    """List all strategies with their currently active preset."""
    result = await db.execute(
        select(Strategy).order_by(Strategy.name)
    )
    strategies = result.scalars().all()
    return StrategyListResponse(
        strategies=[StrategyResponse.model_validate(s) for s in strategies],
        total=len(strategies),
    )


@router.get("/{strategy_name}", response_model=StrategyWithPresets)
async def get_strategy_detail(
    strategy_name: str,
    db: DatabaseSession,
    _admin: CurrentAdminUser,
):
    """Get a strategy with all its presets."""
    result = await db.execute(
        select(Strategy)
        .options(selectinload(Strategy.presets))
        .where(Strategy.name == strategy_name)
    )
    strategy = result.scalars().first()
    if not strategy:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Strategy '{strategy_name}' not found")
    return StrategyWithPresets.model_validate(strategy)


@router.patch("/{strategy_name}/active-preset", response_model=StrategyResponse)
async def update_active_preset(
    strategy_name: str,
    body: StrategyActivePresetUpdate,
    db: DatabaseSession,
    _admin: CurrentAdminUser,
):
    """Set or clear the active preset for a strategy."""
    result = await db.execute(
        select(Strategy).where(Strategy.name == strategy_name)
    )
    strategy = result.scalars().first()
    if not strategy:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Strategy '{strategy_name}' not found")

    if body.active_preset_id is not None:
        # Validate that the preset belongs to this strategy
        preset_result = await db.execute(
            select(StrategyPreset).where(
                StrategyPreset.id == body.active_preset_id,
                StrategyPreset.strategy_id == strategy.id,
            )
        )
        if not preset_result.scalars().first():
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Preset does not belong to this strategy",
            )

    strategy.active_preset_id = body.active_preset_id
    await db.commit()
    await db.refresh(strategy)
    return StrategyResponse.model_validate(strategy)


# ─── StrategyPreset endpoints ────────────────────────────────────

@router.get("/{strategy_name}/presets", response_model=StrategyPresetListResponse)
async def list_presets(
    strategy_name: str,
    db: DatabaseSession,
    _admin: CurrentAdminUser,
):
    """List all presets for a strategy."""
    strategy = await _get_strategy(db, strategy_name)
    result = await db.execute(
        select(StrategyPreset)
        .where(StrategyPreset.strategy_id == strategy.id)
        .order_by(StrategyPreset.name)
    )
    presets = result.scalars().all()
    return StrategyPresetListResponse(
        presets=[StrategyPresetResponse.model_validate(p) for p in presets],
        total=len(presets),
    )


@router.post(
    "/{strategy_name}/presets",
    response_model=StrategyPresetResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_preset(
    strategy_name: str,
    body: StrategyPresetCreate,
    db: DatabaseSession,
    _admin: CurrentAdminUser,
):
    """Add a new preset to a strategy."""
    strategy = await _get_strategy(db, strategy_name)

    # Check duplicate name
    existing = await db.execute(
        select(StrategyPreset).where(
            StrategyPreset.strategy_id == strategy.id,
            StrategyPreset.name == body.name,
        )
    )
    if existing.scalars().first():
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Preset '{body.name}' already exists for strategy '{strategy_name}'",
        )

    if body.parameters is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Parameters field is required",
        )

    preset = StrategyPreset(
        strategy_id=strategy.id,
        name=body.name,
        description=body.description,
        parameters=body.parameters,
    )
    db.add(preset)
    await db.commit()
    await db.refresh(preset)
    return StrategyPresetResponse.model_validate(preset)


@router.put(
    "/{strategy_name}/presets/batch",
    response_model=StrategyPresetListResponse,
)
async def batch_update_presets(
    strategy_name: str,
    body: StrategyPresetBatchUpdate,
    db: DatabaseSession,
    _admin: CurrentAdminUser,
):
    """
    Batch upsert presets for a strategy.
    Existing presets (matched by name) are updated; new ones are created.
    """
    strategy = await _get_strategy(db, strategy_name)

    result = await db.execute(
        select(StrategyPreset).where(StrategyPreset.strategy_id == strategy.id)
    )
    existing_map = {p.name: p for p in result.scalars().all()}

    touched = []
    for item in body.presets:
        if item.name in existing_map:
            preset = existing_map[item.name]
            preset.description = item.description
            preset.parameters = item.parameters
        else:
            preset = StrategyPreset(
                strategy_id=strategy.id,
                name=item.name,
                description=item.description,
                parameters=item.parameters,
            )
            db.add(preset)
        touched.append(preset)

    await db.commit()
    for p in touched:
        await db.refresh(p)

    return StrategyPresetListResponse(
        presets=[StrategyPresetResponse.model_validate(p) for p in touched],
        total=len(touched),
    )


@router.delete(
    "/{strategy_name}/presets/{preset_name}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_preset(
    strategy_name: str,
    preset_name: str,
    db: DatabaseSession,
    _admin: CurrentAdminUser,
):
    """Remove a preset from a strategy. Cannot remove the currently active preset."""
    strategy = await _get_strategy(db, strategy_name)

    result = await db.execute(
        select(StrategyPreset).where(
            StrategyPreset.strategy_id == strategy.id,
            StrategyPreset.name == preset_name,
        )
    )
    preset = result.scalars().first()
    if not preset:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Preset '{preset_name}' not found for strategy '{strategy_name}'",
        )

    if strategy.active_preset_id == preset.id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Cannot remove the currently active preset. Change active preset first.",
        )

    await db.delete(preset)
    await db.commit()


# ─── helpers ─────────────────────────────────────────────────────

async def _get_strategy(db, strategy_name: str) -> Strategy:
    result = await db.execute(
        select(Strategy).where(Strategy.name == strategy_name)
    )
    strategy = result.scalars().first()
    if not strategy:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Strategy '{strategy_name}' not found")
    return strategy
