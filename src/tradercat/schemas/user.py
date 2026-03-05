"""User schemas for API request/response."""
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field, EmailStr


class UserBase(BaseModel):
    """Base user schema."""
    username: str = Field(..., min_length=3, max_length=100)
    email: EmailStr


class UserCreate(UserBase):
    """Schema for creating a user."""
    role: str = Field(default="user", pattern="^(admin|user)$")
    max_symbols: int = Field(default=50, ge=1, le=1000)
    preferred_lang: str | None = Field(None, max_length=10, description="Preferred language (e.g. en, zh)")


class UserUpdate(BaseModel):
    """Schema for updating a user."""
    email: EmailStr | None = None
    role: str | None = Field(None, pattern="^(admin|user)$")
    is_active: bool | None = None
    max_symbols: int | None = Field(None, ge=1, le=1000)
    preferred_lang: str | None = Field(None, max_length=10)


class UserResponse(UserBase):
    """Schema for user response."""
    id: UUID
    role: str
    is_active: bool
    max_symbols: int
    preferred_lang: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    """Schema for personal access token response."""
    id: UUID
    key_prefix: str
    name: str
    is_active: bool
    created_at: datetime
    last_used_at: datetime | None

    model_config = {"from_attributes": True}


class TokenCreate(BaseModel):
    """Schema for creating a personal access token."""
    name: str = Field(default="default", max_length=100)


class TokenCreated(BaseModel):
    """Schema for newly created token (includes plaintext token)."""
    token: str = Field(..., description="Plaintext personal access token - save it, won't be shown again")
    key_prefix: str
    name: str
    created_at: datetime


class UserWithTokens(UserResponse):
    """User response with personal access tokens."""
    tokens: list[TokenResponse] = []

    model_config = {"from_attributes": True}


# Backward-compatible aliases
ApiKeyResponse = TokenResponse
ApiKeyCreate = TokenCreate
ApiKeyCreated = TokenCreated
UserWithKeys = UserWithTokens
