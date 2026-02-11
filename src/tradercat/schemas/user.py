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


class UserUpdate(BaseModel):
    """Schema for updating a user."""
    email: EmailStr | None = None
    role: str | None = Field(None, pattern="^(admin|user)$")
    is_active: bool | None = None
    max_symbols: int | None = Field(None, ge=1, le=1000)


class UserResponse(UserBase):
    """Schema for user response."""
    id: UUID
    role: str
    is_active: bool
    max_symbols: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ApiKeyResponse(BaseModel):
    """Schema for API key response."""
    id: UUID
    key_prefix: str
    name: str
    is_active: bool
    created_at: datetime
    last_used_at: datetime | None

    model_config = {"from_attributes": True}


class ApiKeyCreate(BaseModel):
    """Schema for creating an API key."""
    name: str = Field(default="default", max_length=100)


class ApiKeyCreated(BaseModel):
    """Schema for newly created API key (includes plaintext key)."""
    api_key: str = Field(..., description="Plaintext API key - save it, won't be shown again")
    key_prefix: str
    name: str
    created_at: datetime


class UserWithKeys(UserResponse):
    """User response with API keys."""
    api_keys: list[ApiKeyResponse] = []

    model_config = {"from_attributes": True}
