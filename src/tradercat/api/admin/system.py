"""Admin system API endpoints."""
from fastapi import APIRouter
from pydantic import BaseModel

from tradercat.config import settings

router = APIRouter(prefix="/system", tags=["admin-system"])


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    version: str
    database: str


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """
    Public health check endpoint (no authentication required).
    """
    # TODO: Add actual database health check
    db_status = "connected"
    
    return HealthResponse(
        status="healthy",
        version=settings.api_version,
        database=db_status
    )
