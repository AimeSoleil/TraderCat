"""Report models."""
from datetime import datetime, date
from uuid import uuid4
from sqlalchemy import Column, String, Text, Date, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from tradercat.database import Base


class Report(Base):
    """Report - LLM-generated analysis reports."""
    __tablename__ = "reports"
    __table_args__ = (
        Index("ix_report_user_run_date_symbol", "user_id", "run_date", "symbol"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    run_date = Column(Date, nullable=False, index=True)
    symbol = Column(String(20), nullable=False)
    report_type = Column(String(50), default="symbol_analysis", nullable=False)  # "symbol_analysis" | "daily_summary"
    content_md = Column(Text, nullable=False)  # Raw LLM markdown
    model_used = Column(String(100), nullable=True)
    persona_used = Column(String(50), nullable=True)
    input_context = Column(JSONB, nullable=True)  # Snapshot of signal data sent to LLM
    pipeline_run_id = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    user = relationship("User", back_populates="reports")
