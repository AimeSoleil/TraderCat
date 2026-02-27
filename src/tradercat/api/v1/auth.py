"""JWT-based authentication.

Flow:
1. User submits personal access token (PAT) via POST /api/v1/auth/login
2. Backend validates the token and returns a signed JWT
3. All subsequent requests use Authorization: Bearer <token>
4. Protected endpoints verify the JWT to identify the user
"""
import jwt
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from tradercat.api.deps import CurrentUser, DatabaseSession

from tradercat.config import settings
from tradercat.models import User, PersonalAccessToken
from tradercat.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

# JWT configuration from centralised Settings
JWT_SECRET = settings.jwt_secret
JWT_ALGORITHM = settings.jwt_algorithm
JWT_EXPIRY_MINUTES = settings.jwt_expire_minutes

# ── Schemas ───────────────────────────────────────────────────

class LoginRequest(BaseModel):
    """Login with a personal access token."""
    token: str

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

# ── Endpoints ─────────────────────────────────────────────────

@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, db: DatabaseSession):
    """
    Authenticate with a personal access token and receive a JWT.

    The returned JWT should be sent as `Authorization: Bearer <token>`
    in subsequent requests.
    """
    key_hash = PersonalAccessToken.hash_key(body.token)

    result = await db.execute(
        select(PersonalAccessToken).where(
            PersonalAccessToken.key_hash == key_hash,
            PersonalAccessToken.is_active == True,
        )
    )
    pat = result.scalars().first()
    if not pat:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or inactive token",
        )

    result = await db.execute(
        select(User).where(User.id == pat.user_id, User.is_active == True)
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
async def get_me(current_user: CurrentUser):
    """Return current user info from JWT. Used by the portal to validate sessions."""
    return UserInfo(
        id=str(current_user.id),
        username=current_user.username,
        email=current_user.email,
        role=current_user.role,
    )
