"""LLM token management API — Admin only.

Only administrators can create, view, update, or remove LLM tokens.
Setting ``is_active=True`` on a token will deactivate all other tokens
for that user automatically.
"""
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from tradercat.api.deps import CurrentAdminUser, DatabaseSession
from tradercat.models import LlmToken
from tradercat.schemas.llm_token import (
    LlmTokenCreate,
    LlmTokenUpdate,
    LlmTokenResponse,
    LlmTokenListResponse,
)
from tradercat.logger.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/llm-tokens", tags=["admin-llm-tokens"])


# ── Helpers ───────────────────────────────────────────────────

def _mask_token(token: str) -> str:
    """Return a masked preview like 'sk-****abcd'."""
    if len(token) <= 8:
        return token[:2] + "****"
    return token[:4] + "****" + token[-4:]


def _to_response(t: LlmToken) -> LlmTokenResponse:
    return LlmTokenResponse(
        id=str(t.id),
        provider_name=t.provider_name,
        token_preview=_mask_token(t.token),
        description=t.description,
        is_active=t.is_active,
        created_at=t.created_at,
        updated_at=t.updated_at,
    )


# ── Endpoints ─────────────────────────────────────────────────

@router.get("", response_model=LlmTokenListResponse)
async def list_tokens(
    db: DatabaseSession,
    admin: CurrentAdminUser,
):
    """List all LLM tokens for the admin user."""
    result = await db.execute(
        select(LlmToken)
        .where(LlmToken.user_id == admin.id)
        .order_by(LlmToken.created_at.desc())
    )
    tokens = result.scalars().all()
    return LlmTokenListResponse(
        items=[_to_response(t) for t in tokens],
        total=len(tokens),
    )


@router.post("", response_model=LlmTokenResponse, status_code=status.HTTP_201_CREATED)
async def add_token(
    body: LlmTokenCreate,
    db: DatabaseSession,
    admin: CurrentAdminUser,
):
    """Add a new LLM token. If ``is_active=True``, other tokens are deactivated."""
    from uuid import uuid4

    # If this token should be active, deactivate all others first
    if body.is_active:
        await db.execute(
            update(LlmToken)
            .where(LlmToken.user_id == admin.id, LlmToken.is_active == True)
            .values(is_active=False)
        )

    token = LlmToken(
        id=uuid4(),
        user_id=admin.id,
        provider_name=body.provider_name,
        token=body.token,
        description=body.description,
        is_active=body.is_active,
    )
    db.add(token)
    await db.commit()
    await db.refresh(token)

    logger.info(f"Admin {admin.username} added LLM token for {body.provider_name}")
    return _to_response(token)


@router.patch("/{token_id}", response_model=LlmTokenResponse)
async def update_token(
    token_id: str,
    body: LlmTokenUpdate,
    db: DatabaseSession,
    admin: CurrentAdminUser,
):
    """Update description or active status of a token.

    Setting ``is_active=True`` deactivates all other tokens for the user.
    """
    result = await db.execute(
        select(LlmToken).where(LlmToken.id == token_id, LlmToken.user_id == admin.id)
    )
    token = result.scalars().first()
    if not token:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Token not found")

    if body.description is not None:
        token.description = body.description

    if body.is_active is not None:
        if body.is_active:
            # Deactivate all others first
            await db.execute(
                update(LlmToken)
                .where(LlmToken.user_id == admin.id, LlmToken.is_active == True)
                .values(is_active=False)
            )
        token.is_active = body.is_active

    await db.commit()
    await db.refresh(token)
    return _to_response(token)


@router.delete("/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_token(
    token_id: str,
    db: DatabaseSession,
    admin: CurrentAdminUser,
):
    """Remove an LLM token."""
    result = await db.execute(
        select(LlmToken).where(LlmToken.id == token_id, LlmToken.user_id == admin.id)
    )
    token = result.scalars().first()
    if not token:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Token not found")

    await db.delete(token)
    await db.commit()
    logger.info(f"Admin {admin.username} removed LLM token {token_id}")
