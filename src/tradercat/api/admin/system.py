"""Admin system API endpoints."""
from fastapi import APIRouter
from fastapi.security import HTTPBearer
from pydantic import BaseModel

from tradercat.config import settings

router = APIRouter(prefix="/system", tags=["admin-system"])


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    version: str
    database: str


@router.get("/health", response_model=HealthResponse, dependencies=[])
async def health_check():
    """
    Public health check endpoint (no authentication required).
    
    This endpoint does not require an API key and can be used
    for monitoring and load balancer health checks.
    """
    # TODO: Add actual database health check
    db_status = "connected"
    
    return HealthResponse(
        status="healthy",
        version=settings.api_version,
        database=db_status
    )
