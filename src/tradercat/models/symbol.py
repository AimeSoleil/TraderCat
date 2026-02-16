"""Watchlist/Symbol models."""
from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import Column, String, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from tradercat.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class GlobalSymbol(Base):
    """Global symbol tracked by the pipeline for signal generation."""
    __tablename__ = "global_symbols"
    __table_args__ = (
        UniqueConstraint("symbol", name="uq_global_symbol"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    symbol = Column(String(20), nullable=False, index=True)
    symbol_type = Column(String(20), nullable=False, index=True)  # "macro" or "sector"
    description = Column(String(255), nullable=True)
    added_at = Column(DateTime, default=utcnow, nullable=False)


class WatchlistItem(Base):
    """Watchlist item - symbols tracked by users."""
    __tablename__ = "watchlist_items"
    __table_args__ = (
        UniqueConstraint("user_id", "symbol", name="uq_user_symbol"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    description = Column(String(255), nullable=True)
    added_at = Column(DateTime, default=utcnow, nullable=False)

    # Relationships
    user = relationship("User", back_populates="watchlist")
