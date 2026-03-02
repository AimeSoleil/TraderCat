"""Symbol execution plan models — P3 pipeline output.

Stores per-symbol options execution plans produced by OptionsStrategistRole.
One record per (run_date, symbol) pair.
"""
from datetime import datetime, date, timezone
from uuid import uuid4
from sqlalchemy import Column, String, Text, Date, DateTime, Index, UniqueConstraint, JSON
from sqlalchemy.dialects.postgresql import UUID, JSONB

from tradercat.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class SymbolExecutionPlan(Base):
    """
    Symbol execution plan — LLM-generated per-symbol analysis from P3.

    Contains the 7-gate audit, options strategy selection, trade construction,
    and risk parameters for a single symbol on a given run_date.
    """
    __tablename__ = "symbol_execution_plans"
    __table_args__ = (
        UniqueConstraint("run_date", "symbol", name="uq_exec_plan_run_date_symbol"),
        Index("ix_exec_plan_run_date_symbol", "run_date", "symbol"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    run_date = Column(Date, nullable=False, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    verdict = Column(String(20), nullable=True)  # "buy", "sell", "hold", "watchlist", "reject"
    setup_quality = Column(String(10), nullable=True)  # "A+", "A", "B+", "B", "C", "REJECT"
    content_md = Column(Text, nullable=False)  # Full LLM-generated markdown report
    model_used = Column(String(100), nullable=True)
    identity_used = Column(String(50), nullable=True)
    input_context = Column(
        JSONB().with_variant(JSON, "sqlite"),
        nullable=True,
    )  # Snapshot of signal data sent to LLM
    structured_json = Column(
        JSONB().with_variant(JSON, "sqlite"),
        nullable=True,
    )  # P3 structured data: direction, quality, execution (structure, legs, entry/stop/target, risk)
    pipeline_run_id = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)
