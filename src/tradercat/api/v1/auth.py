"""JWT-based authentication for the web portal.

Flow:
1. User submits API key via POST /api/v1/auth/login
2. Backend validates the key and returns a signed JWT
3. Frontend stores the JWT and sends it via Authorization: Bearer <token>
4. Protected endpoints verify the JWT to identify the user
"""
import jwt
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tradercat.api.deps import DatabaseSession
import logging

from tradercat.config import settings
from tradercat.models import User, ApiKey
from tradercat.logger.logger import get_logger

# Set up logger
use_json = settings.log_format == "json"
logger = get_logger(__name__, level=getattr(logging, settings.log_level), use_json=use_json)

router = APIRouter(prefix="/auth", tags=["auth"])

# JWT configuration from centralised Settings
JWT_SECRET = settings.jwt_secret
JWT_ALGORITHM = settings.jwt_algorithm
JWT_EXPIRY_MINUTES = settings.jwt_expire_minutes

# Bearer token security scheme for Swagger UI
bearer_scheme = HTTPBearer(auto_error=False)


# ── Schemas ───────────────────────────────────────────────────

class LoginRequest(BaseModel):
    """Login with an API key."""
    api_key: str


class LoginResponse(BaseModel):
    """JWT token response."""
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds
    user: "UserInfo"


class UserInfo(BaseModel):
    """Minimal user info returned on login."""
    id: str
    username: str
    email: str
    role: str


# ── Helpers ───────────────────────────────────────────────────

def create_jwt(user: User) -> tuple[str, int]:
    """Create a signed JWT for the given user.

    Returns (token_string, expires_in_seconds).
    """
    expires_in = JWT_EXPIRY_MINUTES * 60
    payload = {
        "sub": str(user.id),
        "username": user.username,
        "role": user.role,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=JWT_EXPIRY_MINUTES),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return token, expires_in


def decode_jwt(token: str) -> dict:
    """Decode and verify a JWT. Raises on invalid/expired."""
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


# ── Dependency: get user from JWT ─────────────────────────────

async def get_current_user_from_jwt(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(DatabaseSession),
) -> User:
    """Resolve user from a Bearer JWT token."""
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    payload = decode_jwt(credentials.credentials)
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


# ── Endpoints ─────────────────────────────────────────────────

@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, db: DatabaseSession):
    """
    Authenticate with an API key and receive a JWT token.

    The returned token should be sent as `Authorization: Bearer <token>`
    in subsequent requests to the web portal API.
    """
    key_hash = ApiKey.hash_key(body.api_key)

    result = await db.execute(
        select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.is_active == True)
    )
    api_key = result.scalars().first()
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or inactive API key",
        )

    result = await db.execute(
        select(User).where(User.id == api_key.user_id, User.is_active == True)
    )
    user = result.scalars().first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    token, expires_in = create_jwt(user)
    logger.info(f"User {user.username} logged in via web portal")

    return LoginResponse(
        access_token=token,
        expires_in=expires_in,
        user=UserInfo(
            id=str(user.id),
            username=user.username,
            email=user.email,
            role=user.role,
        ),
    )


@router.get("/me", response_model=UserInfo)
async def get_me(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: DatabaseSession = None,
):
    """Return current user info from JWT. Used by the portal to validate sessions."""
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    payload = decode_jwt(credentials.credentials)
    user_id = payload.get("sub")

    result = await db.execute(
        select(User).where(User.id == user_id, User.is_active == True)
    )
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    return UserInfo(
        id=str(user.id),
        username=user.username,
        email=user.email,
        role=user.role,
    )
