"""Signal API endpoints."""
from datetime import date
from fastapi import APIRouter, Query
from sqlalchemy import select, func, or_

from tradercat.api.deps import CurrentUser, DatabaseSession
from tradercat.models import SignalRecord, WatchlistItem, SignalScope
from tradercat.schemas.signal import SignalResponse, SignalList

router = APIRouter(prefix="/signals", tags=["signals"])


@router.get("", response_model=SignalList)
async def query_signals(
    db: DatabaseSession,
    current_user: CurrentUser,
    run_date: date | None = Query(None, description="Filter by run date"),
    symbol: str | None = Query(None, max_length=20, description="Filter by symbol"),
    strategy: str | None = Query(None, max_length=100, description="Filter by strategy"),
    signal: str | None = Query(None, description="Filter by signal type (buy/sell/hold)"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0)
):
    """
    Query trading signals.
    Users see:
    - GLOBAL signals (for predefined global symbols)
    - USER signals for symbols in their watchlist
    """
    # Get user's watchlist symbols
    watchlist_result = await db.execute(
        select(WatchlistItem.symbol).where(WatchlistItem.user_id == current_user.id)
    )
    watchlist_symbols = [row[0] for row in watchlist_result.all()]
    
    # Build query: GLOBAL signals OR USER signals for watchlist symbols
    query = select(SignalRecord).where(
        or_(
            SignalRecord.scope == SignalScope.GLOBAL,
            (SignalRecord.scope == SignalScope.USER) & (SignalRecord.symbol.in_(watchlist_symbols))
        )
    )
    
    # Apply filters
    if run_date:
        query = query.where(SignalRecord.run_date == run_date)
    if symbol:
        query = query.where(SignalRecord.symbol == symbol.upper())
    if strategy:
        query = query.where(SignalRecord.strategy == strategy)
    if signal:
        query = query.where(SignalRecord.signal == signal.lower())
    
    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    
    # Get signals with pagination, ordered by date desc
    query = query.order_by(SignalRecord.run_date.desc(), SignalRecord.created_at.desc())
    query = query.offset(offset).limit(limit)
    result = await db.execute(query)
    signals = result.scalars().all()
    
    return SignalList(signals=signals, total=total)
