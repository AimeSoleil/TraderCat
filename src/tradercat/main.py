"""FastAPI application entry point."""
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi

from tradercat.config import settings
from tradercat.database import init_db
from tradercat.logger import get_logger, init_llm_logger

# Import routers
from tradercat.api.v1 import auth, users, watchlist, signals, reports
from tradercat.api.admin import pipeline, system
from tradercat.api.admin import global_symbols as admin_global_symbols
from tradercat.api.admin import strategies as admin_strategies
from tradercat.api.admin import llm_tokens as admin_llm_tokens

logger = get_logger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager for FastAPI app."""
    logger.info("Starting TraderCat API...")
    logger.info(f"Run mode: {settings.run_mode}")
    
    # Initialize database (create tables if they don't exist)
    # Note: In production, use Alembic migrations instead
    try:
        await init_db()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise
    
    # Initialize LLM progress logger
    try:
        init_llm_logger()
        logger.info("LLM progress logger initialized")
    except Exception as e:
        logger.warning(f"Failed to initialize LLM progress logger: {e}")
    
    # Conditionally start pipeline scheduler based on RUN_MODE
    # NOTE: In production, use RUN_MODE=api-only for API service
    # and run a separate pipeline-worker container with RUN_MODE=scheduler
    scheduler_started = False
    if settings.run_mode == "combined":
        # Legacy mode: both API and scheduler in one process
        logger.warning(
            "Running in COMBINED mode - not recommended for production. "
            "Use separate services with RUN_MODE=api-only and RUN_MODE=scheduler"
        )
        try:
            from tradercat.pipeline.scheduler import start_scheduler
            start_scheduler()
            logger.info(f"Pipeline scheduler started (mode: {settings.run_mode})")
            scheduler_started = True
        except Exception as e:
            logger.warning(f"Failed to start pipeline scheduler: {e}")
    elif settings.run_mode == "scheduler":
        # This should not happen - scheduler mode should use pipeline.runner
        logger.error(
            "RUN_MODE=scheduler detected in API service. "
            "Use 'python -m tradercat.pipeline.runner' instead of main.py"
        )
        raise ValueError("Invalid RUN_MODE for API service")
    else:  # api-only
        logger.info(f"Pipeline scheduler disabled (mode: {settings.run_mode})")
        logger.info("Manual pipeline triggers available via /api/admin/pipeline/trigger")
    
    yield
    
    # Shutdown
    logger.info("Shutting down TraderCat API...")
    if scheduler_started:
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
    contact=settings.api_contact,
    license_info=settings.api_license,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    swagger_ui_parameters={
        "defaultModelsExpandDepth": 1,
        "displayRequestDuration": True,
        "filter": True,
        "syntaxHighlight.theme": "monokai",
        "tryItOutEnabled": True,
        "persistAuthorization": True,
    },
    openapi_tags=[
        {
            "name": "users",
            "description": "User management operations (Admin only). Create users and manage personal access tokens.",
        },
        {
            "name": "watchlist",
            "description": "Manage user watchlist. Add/remove symbols to track for signal generation.",
        },
        {
            "name": "admin-strategies",
            "description": "Strategy management (Admin only). View and configure trading strategy parameters.",
        },
        {
            "name": "signals",
            "description": "Query trading signals. Access global signals and user-specific signals.",
        },
        {
            "name": "reports",
            "description": "Access LLM-generated market analysis reports per symbol.",
        },
        {
            "name": "admin-pipeline",
            "description": "Pipeline management (Admin only). Trigger and monitor signal generation pipeline.",
        },
        {
            "name": "admin-system",
            "description": "System operations. Health checks and system information.",
        },
        {
            "name": "admin-llm-tokens",
            "description": "LLM token management (Admin only). Store and manage API keys for LLM providers.",
        },
        {
            "name": "admin-global-symbols",
            "description": "Global symbol management (Admin only). Manage macro/sector symbols used by the pipeline.",
        },
    ],
)

def custom_openapi():
    """Customize OpenAPI schema with security schemes."""
    if app.openapi_schema:
        return app.openapi_schema
    
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
        contact=app.contact,
        license_info=app.license_info,
        tags=app.openapi_tags,
    )
    
    # Set up security schemes — JWT Bearer only
    schemes = openapi_schema.setdefault("components", {}).setdefault("securitySchemes", {})
    # Remove legacy API-Key scheme if FastAPI auto-generated it
    schemes.pop("ApiKeyHeader", None)

    schemes["HTTPBearer"] = {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
        "description": (
            "JWT authentication. "
            "First call POST /api/v1/auth/login with your API key to get a token, "
            "then click 'Authorize' and paste the token here."
        ),
    }
    
    # Use relative URL so Swagger always targets the host the user is accessing
    openapi_schema["servers"] = [
        {
            "url": "/",
            "description": "Current server"
        }
    ]
    
    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: restrict in production
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
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
app.include_router(auth.router, prefix="/api/v1")
app.include_router(users.router, prefix="/api/v1")
app.include_router(watchlist.router, prefix="/api/v1")
app.include_router(signals.router, prefix="/api/v1")
app.include_router(reports.router, prefix="/api/v1")
app.include_router(admin_llm_tokens.router, prefix="/api/admin")
app.include_router(pipeline.router, prefix="/api/admin")
app.include_router(system.router, prefix="/api/admin")
app.include_router(admin_global_symbols.router, prefix="/api/admin")
app.include_router(admin_strategies.router, prefix="/api/admin")

@app.get("/", tags=["root"], dependencies=[])
async def root():
    """
    Root endpoint with API information and quick links.
    
    Returns basic information about the API and links to documentation.
    This endpoint is public and does not require authentication.
    """
    return {
        "name": settings.api_title,
        "version": settings.api_version,
        "description": "Multi-tenant trading signal and report generation API",
        "documentation": {
            "swagger_ui": "/docs",
            "redoc": "/redoc",
            "openapi_schema": "/openapi.json"
        },
        "endpoints": {
            "health": "/api/admin/system/health",
            "users": "/api/v1/users",
            "watchlist": "/api/v1/watchlist",
            "strategies": "/api/admin/strategies",
            "signals": "/api/v1/signals",
            "reports": "/api/v1/reports"
        },
        "authentication": "JWT Bearer token required. Login via POST /api/v1/auth/login with your API key to obtain a token."
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
