"""User report models - personalized reports generated in Q3 pipeline phase."""
from datetime import datetime, date
from uuid import uuid4
from sqlalchemy import Column, String, Text, Date, DateTime, ForeignKey, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from tradercat.database import Base


class UserReport(Base):
    """
    User report - LLM-generated personalized reports from Q3 pipeline phase.
    
    Combines the global macro summary + relevant symbol execution plans,
    then re-processed by LLM with the user's preferred persona.
    
    report_type values:
        - "personalized_briefing": Per-user daily briefing
    """
    __tablename__ = "user_reports"
    __table_args__ = (
        UniqueConstraint("user_id", "run_date", "report_type", name="uq_user_report_user_run_date_type"),
        Index("ix_user_report_user_run_date", "user_id", "run_date"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    run_date = Column(Date, nullable=False, index=True)
    report_type = Column(String(50), default="personalized_briefing", nullable=False)
    content_md = Column(Text, nullable=False)  # LLM-generated markdown
    model_used = Column(String(100), nullable=True)
    identity_used = Column(String(50), nullable=True)
    input_context = Column(JSONB, nullable=True)  # Snapshot: summary + symbol plans used
    pipeline_run_id = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    user = relationship("User", back_populates="user_reports")
