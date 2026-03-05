"""User management API endpoints (Admin only)."""
from uuid import UUID
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select, func
from datetime import datetime

from tradercat.api.deps import CurrentAdminUser, DatabaseSession
from tradercat.models import User, PersonalAccessToken
from tradercat.schemas.user import (
    UserCreate,
    UserUpdate,
    UserResponse,
    UserWithTokens,
    TokenCreated,
    TokenCreate,
    TokenResponse,
)

router = APIRouter(prefix="/users", tags=["users"])


@router.post("", response_model=TokenCreated, status_code=status.HTTP_201_CREATED)
async def create_user(
    user_data: UserCreate,
    db: DatabaseSession,
    admin: CurrentAdminUser
):
    """
    Create a new user and generate a personal access token.
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
    
    # Generate personal access token
    plaintext, key_hash = PersonalAccessToken.generate_key()
    pat = PersonalAccessToken(
        user_id=new_user.id,
        key_hash=key_hash,
        key_prefix=PersonalAccessToken.get_key_prefix(plaintext),
        name="default",
    )
    db.add(pat)
    await db.commit()
    
    return TokenCreated(
        token=plaintext,
        key_prefix=pat.key_prefix,
        name=pat.name,
        created_at=pat.created_at,
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


@router.get("/{user_id}", response_model=UserWithTokens)
async def get_user(
    user_id: UUID,
    db: DatabaseSession,
    admin: CurrentAdminUser
):
    """
    Get user details including personal access tokens.
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
    
    # Load tokens
    result = await db.execute(
        select(PersonalAccessToken).where(PersonalAccessToken.user_id == user_id)
    )
    tokens = result.scalars().all()
    
    return UserWithTokens(
        id=user.id,
        username=user.username,
        email=user.email,
        role=user.role,
        is_active=user.is_active,
        max_symbols=user.max_symbols,
        created_at=user.created_at,
        updated_at=user.updated_at,
        tokens=tokens
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


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: UUID,
    db: DatabaseSession,
    admin: CurrentAdminUser,
):
    """Delete a user and all their API keys. Admin-only."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if user.id == admin.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot delete yourself")

    # Delete tokens first
    keys_result = await db.execute(select(PersonalAccessToken).where(PersonalAccessToken.user_id == user_id))
    for key in keys_result.scalars().all():
        await db.delete(key)
    await db.delete(user)
    await db.commit()


# ── Token management ──────────────────────────────────────────

@router.post("/{user_id}/tokens", response_model=TokenCreated, status_code=status.HTTP_201_CREATED)
async def create_token(
    user_id: UUID,
    body: TokenCreate,
    db: DatabaseSession,
    admin: CurrentAdminUser,
):
    """Generate a new personal access token for a user. Admin-only."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    plaintext, key_hash = PersonalAccessToken.generate_key()
    pat = PersonalAccessToken(
        user_id=user.id,
        key_hash=key_hash,
        key_prefix=PersonalAccessToken.get_key_prefix(plaintext),
        name=body.name,
    )
    db.add(pat)
    await db.commit()

    return TokenCreated(
        token=plaintext,
        key_prefix=pat.key_prefix,
        name=pat.name,
        created_at=pat.created_at,
    )


@router.patch("/{user_id}/tokens/{token_id}", response_model=TokenResponse)
async def toggle_token(
    user_id: UUID,
    token_id: UUID,
    db: DatabaseSession,
    admin: CurrentAdminUser,
):
    """Toggle a personal access token active/inactive. Admin-only."""
    result = await db.execute(
        select(PersonalAccessToken).where(PersonalAccessToken.id == token_id, PersonalAccessToken.user_id == user_id)
    )
    pat = result.scalars().first()
    if not pat:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Token not found")

    pat.is_active = not pat.is_active
    await db.commit()
    await db.refresh(pat)
    return pat


@router.delete("/{user_id}/tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_token(
    user_id: UUID,
    token_id: UUID,
    db: DatabaseSession,
    admin: CurrentAdminUser,
):
    """Delete a personal access token. Admin-only."""
    result = await db.execute(
        select(PersonalAccessToken).where(PersonalAccessToken.id == token_id, PersonalAccessToken.user_id == user_id)
    )
    pat = result.scalars().first()
    if not pat:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Token not found")

    await db.delete(pat)
    await db.commit()
