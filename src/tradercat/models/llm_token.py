"""LLM Token model — per-user API key storage for LLM providers."""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from tradercat.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class LlmToken(Base):
    """Stores user-owned LLM provider API tokens.

    Each user can register multiple tokens across different providers.
    Only **one** token per user can be ``is_active=True`` at a time; that
    token is used when the pipeline runs on behalf of this user (or when
    an admin triggers the pipeline globally).
    """

    __tablename__ = "llm_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider_name = Column(String(100), nullable=False)
    token = Column(String(500), nullable=False)
    description = Column(String(500), nullable=True)
    is_active = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )

    # Relationships
    user = relationship("User", back_populates="llm_tokens")

    __table_args__ = (
        UniqueConstraint("user_id", "provider_name", "token", name="uq_user_provider_token"),
    )

    def __repr__(self) -> str:
        return (
            f"<LlmToken id={self.id} user_id={self.user_id} "
            f"provider={self.provider_name} active={self.is_active}>"
        )
