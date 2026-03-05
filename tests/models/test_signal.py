"""Tests for signal models and scoping."""
import pytest
from datetime import date
from sqlalchemy import select, or_

from tradercat.models import SignalRecord, SignalScope, WatchlistItem


@pytest.mark.asyncio
async def test_create_global_signal(db_session):
    """Test creating a global signal."""
    signal = SignalRecord(
        run_date=date(2026, 2, 11),
        symbol="SPY",
        strategy="momentum",
        signal="buy",
        confidence=0.85,
        reason="Strong uptrend",
        scope=SignalScope.GLOBAL,
    )
    db_session.add(signal)
    await db_session.commit()
    await db_session.refresh(signal)
    
    assert signal.id is not None
    assert signal.scope == SignalScope.GLOBAL
    assert signal.symbol == "SPY"


@pytest.mark.asyncio
async def test_create_user_signal(db_session):
    """Test creating a user-space signal."""
    signal = SignalRecord(
        run_date=date(2026, 2, 11),
        symbol="AAPL",
        strategy="bbands_breakout",
        signal="sell",
        confidence=0.75,
        scope=SignalScope.USER,
    )
    db_session.add(signal)
    await db_session.commit()
    await db_session.refresh(signal)
    
    assert signal.id is not None
    assert signal.scope == SignalScope.USER


@pytest.mark.asyncio
async def test_signal_query_scoping(db_session, test_user):
    """Test signal query with user scoping."""
    # Add symbols to watchlist
    watchlist_symbols = ["AAPL", "MSFT"]
    for symbol in watchlist_symbols:
        item = WatchlistItem(user_id=test_user.id, symbol=symbol)
        db_session.add(item)
    await db_session.commit()
    
    # Create signals
    run_date = date(2026, 2, 11)
    
    # Global signals
    for symbol in ["SPY", "QQQ"]:
        signal = SignalRecord(
            run_date=run_date,
            symbol=symbol,
            strategy="test",
            signal="buy",
            confidence=0.8,
            scope=SignalScope.GLOBAL,
        )
        db_session.add(signal)
    
    # User signals (some in watchlist, some not)
    for symbol in ["AAPL", "MSFT", "GOOGL"]:
        signal = SignalRecord(
            run_date=run_date,
            symbol=symbol,
            strategy="test",
            signal="buy",
            confidence=0.8,
            scope=SignalScope.USER,
        )
        db_session.add(signal)
    
    await db_session.commit()
    
    # Query as user should see:
    # - All GLOBAL signals
    # - USER signals only for watchlist symbols
    
    # Get user's watchlist
    result = await db_session.execute(
        select(WatchlistItem.symbol).where(WatchlistItem.user_id == test_user.id)
    )
    user_symbols = [row[0] for row in result.all()]
    
    # Query signals
    query = select(SignalRecord).where(
        SignalRecord.run_date == run_date
    ).where(
        or_(
            SignalRecord.scope == SignalScope.GLOBAL,
            (SignalRecord.scope == SignalScope.USER) & (SignalRecord.symbol.in_(user_symbols))
        )
    )
    
    result = await db_session.execute(query)
    signals = result.scalars().all()
    
    # Should see: SPY, QQQ (global) + AAPL, MSFT (user watchlist)
    # Should NOT see: GOOGL (user signal but not in watchlist)
    signal_symbols = [s.symbol for s in signals]
    
    assert "SPY" in signal_symbols
    assert "QQQ" in signal_symbols
    assert "AAPL" in signal_symbols
    assert "MSFT" in signal_symbols
    assert "GOOGL" not in signal_symbols
    assert len(signals) == 4
