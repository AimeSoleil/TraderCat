"""Watchlist API endpoints."""
from fastapi import APIRouter, HTTPException, status, Query
from sqlalchemy import select, func

from tradercat.api.deps import CurrentUser, DatabaseSession
from tradercat.models import WatchlistItem
from tradercat.schemas.symbol import (
    WatchlistItemCreate,
    WatchlistItemResponse,
    WatchlistItemList,
    WatchlistBatchImportRequest,
    WatchlistBatchImportResponse,
    WatchlistBatchImportResult,
    WatchlistBatchRemoveRequest,
    WatchlistBatchRemoveResponse,
    WatchlistBatchRemoveResult,
)

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


@router.get("", response_model=WatchlistItemList)
async def list_watchlist(
    db: DatabaseSession,
    current_user: CurrentUser,
    symbol: str | None = Query(None, max_length=20),
    company: str | None = Query(None, max_length=255),
    skip: int = 0,
    limit: int = 100
):
    """
    List user's watchlist symbols with optional filtering.
    """
    query = select(WatchlistItem).where(WatchlistItem.user_id == current_user.id)
    
    if symbol:
        query = query.where(WatchlistItem.symbol.ilike(f"%{symbol}%"))
    if company:
        query = query.where(WatchlistItem.description.ilike(f"%{company}%"))
    
    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    
    # Get items with pagination
    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    items = result.scalars().all()
    
    return WatchlistItemList(items=items, total=total)


@router.post("", response_model=WatchlistItemResponse, status_code=status.HTTP_201_CREATED)
async def add_to_watchlist(
    item: WatchlistItemCreate,
    db: DatabaseSession,
    current_user: CurrentUser
):
    """
    Add a symbol to the user's watchlist.
    Enforces max_symbols limit.
    """
    # Check if symbol already exists for this user
    result = await db.execute(
        select(WatchlistItem).where(
            WatchlistItem.user_id == current_user.id,
            WatchlistItem.symbol == item.symbol.upper()
        )
    )
    existing = result.scalars().first()
    
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Symbol {item.symbol} already in watchlist"
        )
    
    # Check max_symbols limit
    count_result = await db.execute(
        select(func.count()).where(WatchlistItem.user_id == current_user.id)
    )
    current_count = count_result.scalar() or 0
    
    if current_count >= current_user.max_symbols:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Watchlist limit reached ({current_user.max_symbols} symbols max)"
        )
    
    # Add to watchlist
    watchlist_item = WatchlistItem(
        user_id=current_user.id,
        symbol=item.symbol.upper(),
        description=item.description,
    )
    db.add(watchlist_item)
    await db.commit()
    await db.refresh(watchlist_item)
    
    return watchlist_item


@router.post("/batch", response_model=WatchlistBatchImportResponse)
async def batch_import_watchlist(
    payload: WatchlistBatchImportRequest,
    db: DatabaseSession,
    current_user: CurrentUser,
):
    """
    Batch import symbols to the user's watchlist.

    - Skips symbols that already exist in the user's watchlist.
    - Respects the user's max_symbols limit.
    - Returns a per-symbol result summary.
    """
    # Current count
    count_result = await db.execute(
        select(func.count()).where(WatchlistItem.user_id == current_user.id)
    )
    current_count = count_result.scalar() or 0

    # Existing symbols for this user
    existing_result = await db.execute(
        select(WatchlistItem.symbol).where(
            WatchlistItem.user_id == current_user.id
        )
    )
    existing_symbols = {row[0] for row in existing_result.all()}

    created = 0
    skipped = 0
    errors = 0
    results: list[WatchlistBatchImportResult] = []

    # Deduplicate input (keep first occurrence)
    seen: set[str] = set()
    for item in payload.items:
        sym = item.symbol.upper()

        if sym in seen:
            continue
        seen.add(sym)

        # Already exists
        if sym in existing_symbols:
            results.append(WatchlistBatchImportResult(
                symbol=sym, status="exists", detail="Already in watchlist"
            ))
            skipped += 1
            continue

        # Limit check
        if current_count + created >= current_user.max_symbols:
            results.append(WatchlistBatchImportResult(
                symbol=sym, status="error", detail="Watchlist limit reached"
            ))
            errors += 1
            continue

        # Create
        try:
            new_item = WatchlistItem(
                user_id=current_user.id,
                symbol=sym,
                description=item.description,
            )
            db.add(new_item)
            results.append(WatchlistBatchImportResult(symbol=sym, status="created"))
            created += 1
        except Exception as e:
            results.append(WatchlistBatchImportResult(
                symbol=sym, status="error", detail=str(e)
            ))
            errors += 1

    await db.commit()

    return WatchlistBatchImportResponse(
        created=created,
        skipped=skipped,
        errors=errors,
        results=results,
    )


@router.delete("/{symbol}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_from_watchlist(
    symbol: str,
    db: DatabaseSession,
    current_user: CurrentUser
):
    """
    Remove a symbol from the user's watchlist.
    """
    result = await db.execute(
        select(WatchlistItem).where(
            WatchlistItem.user_id == current_user.id,
            WatchlistItem.symbol == symbol.upper()
        )
    )
    item = result.scalars().first()
    
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Symbol {symbol} not found in watchlist"
        )
    
    await db.delete(item)
    await db.commit()
    
    return None


@router.post("/batch-remove", response_model=WatchlistBatchRemoveResponse)
async def batch_remove_from_watchlist(
    payload: WatchlistBatchRemoveRequest,
    db: DatabaseSession,
    current_user: CurrentUser,
):
    """
    Batch remove symbols from the user's watchlist.

    - Skips symbols not found in the user's watchlist.
    - Returns a per-symbol result summary.
    """
    # Normalize and deduplicate
    unique_symbols = list(dict.fromkeys(s.strip().upper() for s in payload.symbols))

    # Fetch all matching items in one query
    result = await db.execute(
        select(WatchlistItem).where(
            WatchlistItem.user_id == current_user.id,
            WatchlistItem.symbol.in_(unique_symbols),
        )
    )
    found_items = {item.symbol: item for item in result.scalars().all()}

    removed = 0
    not_found = 0
    results: list[WatchlistBatchRemoveResult] = []

    for sym in unique_symbols:
        if sym in found_items:
            await db.delete(found_items[sym])
            results.append(WatchlistBatchRemoveResult(symbol=sym, status="removed"))
            removed += 1
        else:
            results.append(WatchlistBatchRemoveResult(symbol=sym, status="not_found"))
            not_found += 1

    await db.commit()

    return WatchlistBatchRemoveResponse(
        removed=removed,
        not_found=not_found,
        results=results,
    )
