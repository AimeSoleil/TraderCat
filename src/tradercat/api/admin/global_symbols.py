"""Admin Global Symbols API — manage pipeline global symbols."""
from fastapi import APIRouter, HTTPException, status, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from datetime import datetime

from tradercat.api.deps import CurrentAdminUser, DatabaseSession
from tradercat.models import GlobalSymbol

router = APIRouter(prefix="/global-symbols", tags=["admin-global-symbols"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class GlobalSymbolItem(BaseModel):
    """Single global symbol for batch operations."""
    symbol: str = Field(..., min_length=1, max_length=20)
    symbol_type: str = Field(..., pattern="^(macro|sector)$", description="'macro' or 'sector'")
    description: str | None = Field(None, max_length=255)


class GlobalSymbolResponse(BaseModel):
    """Response for a single global symbol."""
    id: str
    symbol: str
    symbol_type: str
    description: str | None
    added_at: datetime

    model_config = {"from_attributes": True}


class GlobalSymbolListResponse(BaseModel):
    """Response for listing global symbols."""
    items: list[GlobalSymbolResponse]
    total: int


class BatchAddRequest(BaseModel):
    """Request to batch add global symbols."""
    items: list[GlobalSymbolItem] = Field(..., min_length=1, max_length=200)


class BatchAddResultItem(BaseModel):
    symbol: str
    status: str  # "created", "exists", "error"
    detail: str | None = None


class BatchAddResponse(BaseModel):
    created: int
    skipped: int
    errors: int
    results: list[BatchAddResultItem]


class BatchRemoveRequest(BaseModel):
    """Request to batch remove global symbols."""
    symbols: list[str] = Field(..., min_length=1, max_length=200)


class BatchRemoveResultItem(BaseModel):
    symbol: str
    status: str  # "removed", "not_found"


class BatchRemoveResponse(BaseModel):
    removed: int
    not_found: int
    results: list[BatchRemoveResultItem]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=GlobalSymbolListResponse)
async def list_global_symbols(
    db: DatabaseSession,
    admin: CurrentAdminUser,
    symbol_type: str | None = Query(None, pattern="^(macro|sector)$"),
):
    """
    List all global symbols. Optionally filter by type (macro / sector).
    """
    query = select(GlobalSymbol)
    if symbol_type:
        query = query.where(GlobalSymbol.symbol_type == symbol_type)
    query = query.order_by(GlobalSymbol.symbol_type, GlobalSymbol.symbol)

    result = await db.execute(query)
    items = result.scalars().all()

    return GlobalSymbolListResponse(items=items, total=len(items))


@router.post("/batch", response_model=BatchAddResponse)
async def batch_add_global_symbols(
    payload: BatchAddRequest,
    db: DatabaseSession,
    admin: CurrentAdminUser,
):
    """
    Batch add global symbols.

    - Skips symbols that already exist.
    - Each item requires `symbol`, `symbol_type` ('macro' or 'sector'), and optional `description`.
    """
    # Existing symbols
    existing_result = await db.execute(select(GlobalSymbol.symbol))
    existing = {row[0] for row in existing_result.all()}

    created = 0
    skipped = 0
    errors = 0
    results: list[BatchAddResultItem] = []
    seen: set[str] = set()

    for item in payload.items:
        sym = item.symbol.strip().upper()

        if sym in seen:
            continue
        seen.add(sym)

        if sym in existing:
            results.append(BatchAddResultItem(symbol=sym, status="exists", detail="Already registered"))
            skipped += 1
            continue

        try:
            db.add(GlobalSymbol(
                symbol=sym,
                symbol_type=item.symbol_type,
                description=item.description,
            ))
            results.append(BatchAddResultItem(symbol=sym, status="created"))
            created += 1
        except Exception as e:
            results.append(BatchAddResultItem(symbol=sym, status="error", detail=str(e)))
            errors += 1

    await db.commit()

    return BatchAddResponse(created=created, skipped=skipped, errors=errors, results=results)


@router.post("/batch-remove", response_model=BatchRemoveResponse)
async def batch_remove_global_symbols(
    payload: BatchRemoveRequest,
    db: DatabaseSession,
    admin: CurrentAdminUser,
):
    """
    Batch remove global symbols.
    """
    unique_symbols = list(dict.fromkeys(s.strip().upper() for s in payload.symbols))

    result = await db.execute(
        select(GlobalSymbol).where(GlobalSymbol.symbol.in_(unique_symbols))
    )
    found = {item.symbol: item for item in result.scalars().all()}

    removed = 0
    not_found = 0
    results: list[BatchRemoveResultItem] = []

    for sym in unique_symbols:
        if sym in found:
            await db.delete(found[sym])
            results.append(BatchRemoveResultItem(symbol=sym, status="removed"))
            removed += 1
        else:
            results.append(BatchRemoveResultItem(symbol=sym, status="not_found"))
            not_found += 1

    await db.commit()

    return BatchRemoveResponse(removed=removed, not_found=not_found, results=results)
