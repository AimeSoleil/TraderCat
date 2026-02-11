"""User management API endpoints (Admin only)."""
from uuid import UUID
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select, func
from datetime import datetime

from tradercat.api.deps import CurrentAdminUser, DatabaseSession
from tradercat.models import User, ApiKey
from tradercat.schemas.user import (
    UserCreate,
    UserUpdate,
    UserResponse,
    UserWithKeys,
    ApiKeyCreated,
)

router = APIRouter(prefix="/users", tags=["users"])


@router.post("", response_model=ApiKeyCreated, status_code=status.HTTP_201_CREATED)
async def create_user(
    user_data: UserCreate,
    db: DatabaseSession,
    admin: CurrentAdminUser
):
    """
    Create a new user and generate an API key.
    Admin-only endpoint.
    """
    # Check if username or email already exists
    result = await db.execute(
        select(User).where(
            (User.username == user_data.username) | (User.email == user_data.email)
        )
    )
    existing_user = result.scalars().first()
    
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username or email already exists"
        )
    
    # Create user
    new_user = User(
        username=user_data.username,
        email=user_data.email,
        role=user_data.role,
        max_symbols=user_data.max_symbols,
    )
    db.add(new_user)
    await db.flush()  # Get the user ID
    
    # Generate API key
    plaintext_key, key_hash = ApiKey.generate_key()
    api_key = ApiKey(
        user_id=new_user.id,
        key_hash=key_hash,
        key_prefix=ApiKey.get_key_prefix(plaintext_key),
        name="default",
    )
    db.add(api_key)
    await db.commit()
    
    return ApiKeyCreated(
        api_key=plaintext_key,
        key_prefix=api_key.key_prefix,
        name=api_key.name,
        created_at=api_key.created_at,
    )


@router.get("", response_model=list[UserResponse])
async def list_users(
    db: DatabaseSession,
    admin: CurrentAdminUser,
    skip: int = 0,
    limit: int = 100
):
    """
    List all users.
    Admin-only endpoint.
    """
    result = await db.execute(
        select(User).offset(skip).limit(limit)
    )
    users = result.scalars().all()
    return users


@router.get("/{user_id}", response_model=UserWithKeys)
async def get_user(
    user_id: UUID,
    db: DatabaseSession,
    admin: CurrentAdminUser
):
    """
    Get user details including API keys.
    Admin-only endpoint.
    """
    result = await db.execute(
        select(User).where(User.id == user_id)
    )
    user = result.scalars().first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Load API keys
    result = await db.execute(
        select(ApiKey).where(ApiKey.user_id == user_id)
    )
    api_keys = result.scalars().all()
    
    return UserWithKeys(
        id=user.id,
        username=user.username,
        email=user.email,
        role=user.role,
        is_active=user.is_active,
        max_symbols=user.max_symbols,
        created_at=user.created_at,
        updated_at=user.updated_at,
        api_keys=api_keys
    )


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: UUID,
    user_update: UserUpdate,
    db: DatabaseSession,
    admin: CurrentAdminUser
):
    """
    Update user details.
    Admin-only endpoint.
    """
    result = await db.execute(
        select(User).where(User.id == user_id)
    )
    user = result.scalars().first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Update fields
    update_data = user_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(user, field, value)
    
    user.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(user)
    
    return user
