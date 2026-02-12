"""Global report models - pipeline-generated reports not bound to a specific user."""
from datetime import datetime, date
from uuid import uuid4
from sqlalchemy import Column, String, Text, Date, DateTime, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB

from tradercat.database import Base


class GlobalReport(Base):
    """
    Global report - LLM-generated reports from Q2 pipeline phase.
    
    report_type values:
        - "macro_summary": Macro + sector regime summary (1 per pipeline run)
        - "symbol_execution_plan": Per-symbol execution plan (1 per symbol per run)
    """
    __tablename__ = "global_reports"
    __table_args__ = (
        Index("ix_global_report_run_date_type", "run_date", "report_type"),
        Index("ix_global_report_run_date_symbol", "run_date", "symbol"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    run_date = Column(Date, nullable=False, index=True)
    symbol = Column(String(20), nullable=True)  # NULL for macro_summary, set for symbol_execution_plan
    report_type = Column(String(50), nullable=False)  # "macro_summary" | "symbol_execution_plan"
    content_md = Column(Text, nullable=False)  # LLM-generated markdown
    model_used = Column(String(100), nullable=True)
    persona_used = Column(String(50), nullable=True)
    input_context = Column(JSONB, nullable=True)  # Snapshot of signal data sent to LLM
    pipeline_run_id = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
