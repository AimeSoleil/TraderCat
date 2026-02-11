"""Signal record models."""
from datetime import datetime, date
from uuid import uuid4
from enum import Enum as PyEnum
from sqlalchemy import Column, String, Float, Date, DateTime, Index, Enum
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from tradercat.database import Base


class SignalScope(str, PyEnum):
    """Signal scope enumeration."""
    GLOBAL = "global"
    USER = "user"


class SignalRecord(Base):
    """Signal record - stores generated trading signals."""
    __tablename__ = "signal_records"
    __table_args__ = (
        Index("ix_signal_run_date_symbol", "run_date", "symbol"),
        Index("ix_signal_scope_run_date", "scope", "run_date"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    run_date = Column(Date, nullable=False, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    strategy = Column(String(100), nullable=False)
    signal = Column(String(20), nullable=False)  # "buy", "sell", "hold", "rebalance"
    confidence = Column(Float, default=0.0, nullable=False)
    reason = Column(String(1000), nullable=True)
    details = Column(JSONB, nullable=True)  # Flexible Dict[str, Any] stored as JSONB
    scope = Column(Enum(SignalScope), default=SignalScope.USER, nullable=False)
    pipeline_run_id = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
