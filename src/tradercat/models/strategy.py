"""Strategy configuration models."""
from datetime import datetime
from uuid import uuid4
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from tradercat.database import Base


class StrategyConfig(Base):
    """Strategy configuration - user-level parameter overrides."""
    __tablename__ = "strategy_configs"
    __table_args__ = (
        UniqueConstraint("user_id", "strategy_name", name="uq_user_strategy"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    strategy_name = Column(String(100), nullable=False)
    preset_name = Column(String(100), nullable=True)
    parameters = Column(JSONB, nullable=True)  # User-specific parameter overrides
    is_active = Column(Boolean, default=True, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    user = relationship("User", back_populates="strategy_configs")
