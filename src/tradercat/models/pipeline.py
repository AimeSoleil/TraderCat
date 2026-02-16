"""Pipeline run models."""
from datetime import datetime, date, timezone
from uuid import uuid4
from enum import Enum as PyEnum
from sqlalchemy import Column, String, Integer, Text, Date, DateTime
from sqlalchemy.dialects.postgresql import UUID

from tradercat.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class PipelineStatus(str, PyEnum):
    """Pipeline run status."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class PipelineRun(Base):
    """Pipeline run - tracks nightly pipeline execution."""
    __tablename__ = "pipeline_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    run_date = Column(Date, unique=True, nullable=False, index=True)  # One run per market day
    status = Column(String(20), default=PipelineStatus.PENDING.value, nullable=False)
    step = Column(String(50), nullable=True)  # Current step name
    total_symbols = Column(Integer, default=0, nullable=False)
    processed_symbols = Column(Integer, default=0, nullable=False)
    total_reports = Column(Integer, default=0, nullable=False)
    processed_reports = Column(Integer, default=0, nullable=False)
    error_log = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)
