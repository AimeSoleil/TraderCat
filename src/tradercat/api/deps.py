"""API dependencies for authentication and database sessions."""
from typing import AsyncGenerator, Annotated
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import APIKeyHeader, HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from tradercat.database import get_db
from tradercat.models import User, ApiKey
from datetime import datetime

from tradercat.logger.logger import get_logger
logger = get_logger(__name__)

# Security schemes
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
bearer_scheme = HTTPBearer(auto_error=False)


def _decode_jwt(token: str) -> dict:
    """Decode a JWT token. Imported lazily to avoid circular imports."""
    import jwt as pyjwt
    from tradercat.config import settings
    try:
        return pyjwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except pyjwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


async def get_current_user(
    x_api_key: Annotated[str | None, Depends(api_key_header)] = None,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Authenticate user via JWT Bearer token **or** X-API-Key header.

    Priority: Bearer token first, then API key.
    """
    # ── Path 1: JWT Bearer ──
    if credentials is not None:
        payload = _decode_jwt(credentials.credentials)
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")
        result = await db.execute(
            select(User).where(User.id == user_id, User.is_active == True)
        )
        user = result.scalars().first()
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")
        return user

    # ── Path 2: API Key ──
    if x_api_key is not None:
        key_hash = ApiKey.hash_key(x_api_key)
        result = await db.execute(
            select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.is_active == True)
        )
        api_key = result.scalars().first()
        if not api_key:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or inactive API key")

        api_key.last_used_at = datetime.utcnow()
        await db.commit()

        result = await db.execute(
            select(User).where(User.id == api_key.user_id, User.is_active == True)
        )
        user = result.scalars().first()
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")
        return user

    # ── Neither provided ──
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")


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
