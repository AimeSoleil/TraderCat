"""Macro regime context models — P2 pipeline output.

Stores the global macro regime analysis produced by MacroAnalystRole.
One record per pipeline run date.
"""
from datetime import datetime, date, timezone
from uuid import uuid4
from sqlalchemy import Column, String, Text, Float, Date, DateTime, JSON
from sqlalchemy.dialects.postgresql import UUID, JSONB

from tradercat.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class MacroRegimeContext(Base):
    """
    Macro regime context — LLM-generated regime analysis from P2.

    Contains the global market regime classification, score, sector rotation,
    risk filters, and the full markdown report. One row per run_date.
    """
    __tablename__ = "macro_regime_contexts"
    __table_args__ = ()

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    run_date = Column(Date, nullable=False, unique=True, index=True)
    regime_label = Column(String(50), nullable=True)  # e.g. "Moderate Bull", "Choppy/Transitional"
    regime_score = Column(Float, nullable=True)  # -5.0 to +5.0
    content_md = Column(Text, nullable=False)  # Full LLM-generated markdown report
    downstream_filters = Column(
        JSONB().with_variant(JSON, "sqlite"),
        nullable=True,
    )  # Extracted Section 4: directional_bias, confidence_floor, risk_modifier, cash_reserve, etc.
    model_used = Column(String(100), nullable=True)
    identity_used = Column(String(50), nullable=True)
    input_context = Column(
        JSONB().with_variant(JSON, "sqlite"),
        nullable=True,
    )  # Snapshot of signal data sent to LLM
    pipeline_run_id = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)
