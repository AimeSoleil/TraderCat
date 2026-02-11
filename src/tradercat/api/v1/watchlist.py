"""Watchlist API endpoints."""
from fastapi import APIRouter, HTTPException, status, Query
from sqlalchemy import select, func

from tradercat.api.deps import CurrentUser, DatabaseSession
from tradercat.models import WatchlistItem
from tradercat.schemas.symbol import (
    WatchlistItemCreate,
    WatchlistItemResponse,
    WatchlistItemList,
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
        query = query.where(WatchlistItem.company_name.ilike(f"%{company}%"))
    
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
        company_name=item.company_name,
    )
    db.add(watchlist_item)
    await db.commit()
    await db.refresh(watchlist_item)
    
    return watchlist_item


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
