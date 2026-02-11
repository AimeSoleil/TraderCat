"""FastAPI application entry point."""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from tradercat.config import settings
from tradercat.database import init_db
from tradercat.logger.logger import get_logger

# Import routers
from tradercat.api.v1 import users, watchlist, strategies, signals, reports
from tradercat.api.admin import pipeline, system

# Set up logger
use_json = settings.log_format == "json"
logger = get_logger(__name__, level=getattr(logging, settings.log_level), use_json=use_json)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager for FastAPI app."""
    logger.info("Starting TraderCat API...")
    
    # Initialize database (create tables if they don't exist)
    # Note: In production, use Alembic migrations instead
    try:
        await init_db()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise
    
    # Start pipeline scheduler
    try:
        from tradercat.pipeline.scheduler import start_scheduler
        start_scheduler()
        logger.info("Pipeline scheduler started")
    except Exception as e:
        logger.warning(f"Failed to start pipeline scheduler: {e}")
    
    yield
    
    # Shutdown
    logger.info("Shutting down TraderCat API...")
    try:
        from tradercat.pipeline.scheduler import stop_scheduler
        stop_scheduler()
        logger.info("Pipeline scheduler stopped")
    except Exception:
        pass


# Create FastAPI application
app = FastAPI(
    title=settings.api_title,
    description=settings.api_description,
    version=settings.api_version,
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Exception handlers
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error"}
    )


# Register routers
app.include_router(users.router, prefix="/api/v1")
app.include_router(watchlist.router, prefix="/api/v1")
app.include_router(strategies.router, prefix="/api/v1")
app.include_router(signals.router, prefix="/api/v1")
app.include_router(reports.router, prefix="/api/v1")
app.include_router(pipeline.router, prefix="/api/admin")
app.include_router(system.router, prefix="/api/admin")


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": settings.api_title,
        "version": settings.api_version,
        "docs": "/docs",
        "health": "/api/admin/system/health"
    }


def run_api():
    """Run the FastAPI application with uvicorn."""
    import uvicorn
    uvicorn.run(
        "tradercat.main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_config=None,  # Use our custom logger
    )


if __name__ == "__main__":
    run_api()
