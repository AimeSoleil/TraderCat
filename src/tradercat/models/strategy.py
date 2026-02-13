"""Strategy and StrategyPreset models — global strategy configuration."""
from datetime import datetime
from uuid import uuid4
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from tradercat.database import Base


class Strategy(Base):
    """
    Strategy — a registered trading strategy.

    Each strategy has one active preset at a time (active_preset_id).
    If active_preset_id is NULL, the pipeline falls back to the
    hardcoded default preset and logs a warning.
    """
    __tablename__ = "strategies"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String(100), unique=True, nullable=False, index=True)
    description = Column(String(500), nullable=True)
    strategy_class = Column(String(200), nullable=False)  # e.g. "BollingerBreakoutStrategy"
    default_preset_name = Column(String(100), nullable=False)  # fallback preset name
    active_preset_id = Column(
        UUID(as_uuid=True),
        ForeignKey("strategy_presets.id", ondelete="SET NULL"),
        nullable=True,
    )
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    presets = relationship(
        "StrategyPreset",
        back_populates="strategy",
        foreign_keys="StrategyPreset.strategy_id",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    active_preset = relationship(
        "StrategyPreset",
        foreign_keys=[active_preset_id],
        post_update=True,
        lazy="joined",
    )


class StrategyPreset(Base):
    """
    StrategyPreset — a named parameter configuration for a strategy.

    Each strategy can have multiple presets. Only one is active at a time
    (referenced by Strategy.active_preset_id).
    """
    __tablename__ = "strategy_presets"
    __table_args__ = (
        UniqueConstraint("strategy_id", "name", name="uq_strategy_preset_name"),
        Index("ix_strategy_preset_strategy_id", "strategy_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    strategy_id = Column(
        UUID(as_uuid=True),
        ForeignKey("strategies.id", ondelete="CASCADE"),
        nullable=False,
    )
    name = Column(String(100), nullable=False)
    description = Column(String(500), nullable=True)
    parameters = Column(JSONB, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    strategy = relationship(
        "Strategy",
        back_populates="presets",
        foreign_keys=[strategy_id],
    )
