"""User briefing models — P4 pipeline output.

Stores personalized portfolio briefings produced by SummarizerRole
with a fixed summarizer identity. One record per (user_id, run_date).
"""
from datetime import datetime, date, timezone
from uuid import uuid4
from sqlalchemy import Column, String, Text, Date, DateTime, ForeignKey, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy import JSON
from sqlalchemy.orm import relationship

from tradercat.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class UserBriefing(Base):
    """
    User briefing — LLM-generated personalized portfolio report from P4.

    Combines the macro regime context (P2) + relevant symbol execution plans (P3)
    re-processed by LLM with a fixed summarizer identity.
    """
    __tablename__ = "user_briefings"
    __table_args__ = (
        UniqueConstraint("user_id", "run_date", name="uq_user_briefing_user_run_date"),
        Index("ix_user_briefing_user_run_date", "user_id", "run_date"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    run_date = Column(Date, nullable=False, index=True)
    content_md = Column(Text, nullable=False)  # LLM-generated markdown
    model_used = Column(String(100), nullable=True)
    identity_used = Column(String(50), nullable=True)
    input_context = Column(
        JSONB().with_variant(JSON, "sqlite"),
        nullable=True,
    )  # Snapshot: regime summary + symbol plans used
    pipeline_run_id = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)

    # Relationships
    user = relationship("User", back_populates="user_briefings")
