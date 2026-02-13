"""Tests for watchlist functionality."""
import pytest
from sqlalchemy import select, func

from tradercat.models import WatchlistItem


@pytest.mark.asyncio
async def test_add_watchlist_item(db_session, test_user):
    """Test adding a symbol to watchlist."""
    item = WatchlistItem(
        user_id=test_user.id,
        symbol="AAPL",
        description="Apple Inc.",
    )
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)
    
    assert item.id is not None
    assert item.symbol == "AAPL"
    assert item.description == "Apple Inc."
    assert item.user_id == test_user.id


@pytest.mark.asyncio
async def test_watchlist_unique_constraint(db_session, test_user):
    """Test that user cannot add same symbol twice."""
    item1 = WatchlistItem(user_id=test_user.id, symbol="AAPL")
    db_session.add(item1)
    await db_session.commit()
    
    item2 = WatchlistItem(user_id=test_user.id, symbol="AAPL")
    db_session.add(item2)
    
    with pytest.raises(Exception):  # Should raise integrity error
        await db_session.commit()


@pytest.mark.asyncio
async def test_list_watchlist(db_session, test_user):
    """Test listing user's watchlist."""
    # Add multiple symbols
    symbols = ["AAPL", "GOOGL", "MSFT"]
    for symbol in symbols:
        item = WatchlistItem(user_id=test_user.id, symbol=symbol)
        db_session.add(item)
    await db_session.commit()
    
    # Query watchlist
    result = await db_session.execute(
        select(WatchlistItem).where(WatchlistItem.user_id == test_user.id)
    )
    items = result.scalars().all()
    
    assert len(items) == 3
    item_symbols = [item.symbol for item in items]
    assert "AAPL" in item_symbols
    assert "GOOGL" in item_symbols
    assert "MSFT" in item_symbols


@pytest.mark.asyncio
async def test_watchlist_count(db_session, test_user):
    """Test counting watchlist items."""
    # Add symbols
    for i in range(5):
        item = WatchlistItem(user_id=test_user.id, symbol=f"SYM{i}")
        db_session.add(item)
    await db_session.commit()
    
    # Count items
    result = await db_session.execute(
        select(func.count()).where(WatchlistItem.user_id == test_user.id)
    )
    count = result.scalar()
    
    assert count == 5
