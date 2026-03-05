"""User and Personal Access Token models."""
import hashlib
import secrets
from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import Column, String, Boolean, Integer, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from tradercat.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    """User model for multi-tenant system."""
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    username = Column(String(100), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False)
    role = Column(String(20), default="user", nullable=False)  # "admin" | "user"
    is_active = Column(Boolean, default=True, nullable=False)
    max_symbols = Column(Integer, default=50, nullable=False)
    preferred_lang = Column(String(10), nullable=True)  # e.g. "en", "zh"
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    # Relationships
    tokens = relationship("PersonalAccessToken", back_populates="user", cascade="all, delete-orphan")
    watchlist = relationship("WatchlistItem", back_populates="user", cascade="all, delete-orphan")
    user_briefings = relationship("UserBriefing", back_populates="user", cascade="all, delete-orphan")
    llm_tokens = relationship("LlmToken", back_populates="user", cascade="all, delete-orphan")


# Backward-compatible alias so existing Alembic migrations keep working.
ApiKey = None  # defined after PersonalAccessToken


class PersonalAccessToken(Base):
    """Personal Access Token (PAT) for authentication."""
    __tablename__ = "personal_access_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    key_hash = Column(String(128), unique=True, nullable=False, index=True)  # SHA-256 hash
    key_prefix = Column(String(12), nullable=False)  # "tc_abc..." for display
    name = Column(String(100), default="default", nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    last_used_at = Column(DateTime, nullable=True)

    # Relationships
    user = relationship("User", back_populates="tokens")

    @staticmethod
    def generate_key() -> tuple[str, str]:
        """
        Generate a new personal access token.

        Returns:
            tuple: (plaintext_token, key_hash)
        """
        # Generate random token: tc_ + 32 characters
        plaintext = "tc_" + secrets.token_urlsafe(24)
        key_hash = hashlib.sha256(plaintext.encode()).hexdigest()
        return plaintext, key_hash

    @staticmethod
    def hash_key(plaintext: str) -> str:
        """Hash a personal access token."""
        return hashlib.sha256(plaintext.encode()).hexdigest()

    @staticmethod
    def get_key_prefix(plaintext: str) -> str:
        """Extract prefix for display (first 12 characters)."""
        return plaintext[:12] if len(plaintext) >= 12 else plaintext


# Backward-compatible alias
ApiKey = PersonalAccessToken
