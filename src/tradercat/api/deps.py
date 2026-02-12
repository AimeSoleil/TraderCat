"""API dependencies for authentication and database sessions."""
from typing import AsyncGenerator, Annotated
from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from tradercat.database import get_db
from tradercat.models import User, ApiKey
from datetime import datetime

from tradercat.logger.logger import get_logger
logger = get_logger(__name__)

# Define API Key security scheme
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)

async def get_current_user(
    x_api_key: Annotated[str, Depends(api_key_header)],
    db: AsyncSession = Depends(get_db)
) -> User:
    """
    Authenticate user via API key.
    
    Args:
        x_api_key: API key from X-API-Key header
        db: Database session
        
    Returns:
        Authenticated User object
        
    Raises:
        HTTPException: If authentication fails
    """
    # Hash the provided key
    key_hash = ApiKey.hash_key(x_api_key)
    
    # Look up the API key
    result = await db.execute(
        select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.is_active == True)
    )
    api_key = result.scalars().first()
    
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or inactive API key"
        )
    
    # Update last used timestamp
    api_key.last_used_at = datetime.utcnow()
    await db.commit()
    
    # Get the user
    result = await db.execute(
        select(User).where(User.id == api_key.user_id, User.is_active == True)
    )
    user = result.scalars().first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive"
        )
    
    return user


async def get_current_admin_user(
    current_user: User = Depends(get_current_user)
) -> User:
    """
    Verify that the current user is an admin.
    
    Args:
        current_user: Authenticated user
        
    Returns:
        Admin User object
        
    Raises:
        HTTPException: If user is not an admin
    """
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return current_user


# Type aliases for dependency injection
CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentAdminUser = Annotated[User, Depends(get_current_admin_user)]
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
