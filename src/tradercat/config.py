"""Application configuration using pydantic-settings."""
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Database
    database_url: str = Field(
        default="postgresql+asyncpg://tradercat:tradercat@localhost:5432/tradercat",
        description="PostgreSQL database URL with asyncpg driver"
    )
    
    # API
    api_title: str = "TraderCat API"
    api_version: str = "2.0.0"
    api_description: str = """
## TraderCat Trading Signal & Report Generation API

A production-ready multi-tenant API for trading signal generation and LLM-powered market analysis.

### Features

* 🔐 **JWT Authentication** - Personal access token (PAT) login → Bearer token for all requests
* 👥 **Multi-Tenant** - User-level watchlists and reports
* 📊 **8 Trading Strategies** - Technical analysis with customizable parameters
* 🤖 **AI Reports** - LLM-powered market analysis
* 📅 **Scheduled Pipeline** - Automatic nightly signal generation
* 🎯 **Smart Deduplication** - Global + user-specific signals

### Authentication

1. **Login**: `POST /api/v1/auth/login` with `{ "token": "tc_..." }` → returns a JWT
2. **All other requests**: `Authorization: Bearer <jwt_token>`

Public endpoints: `/`, `/api/admin/system/health`, `/api/v1/auth/login`

### Getting Started

1. **Admin creates user**: `POST /api/v1/users` (returns personal access token)
2. **Login**: `POST /api/v1/auth/login` with the token to get a JWT
3. **Add watchlist symbols**: `POST /api/v1/watchlist`
4. **View signals**: `GET /api/v1/signals`
5. **Read reports**: `GET /api/v1/reports`

### Architecture

- **API Service**: FastAPI with async SQLAlchemy
- **Database**: PostgreSQL with async driver
- **Pipeline**: Standalone scheduler service (8 PM ET)
- **Deployment**: Docker Compose / Kubernetes ready
"""
    api_contact: dict = {
        "name": "TraderCat Support",
        "url": "https://github.com/AimeSoleil/TraderCat",
        "email": "jeaimesoleil@gmail.com"
    }
    api_license: dict = {
        "name": "MIT",
        "url": "https://opensource.org/licenses/MIT"
    }
    
    # Pipeline
    pipeline_schedule_hour: int = Field(default=20, description="Hour to run pipeline (24h format)")
    pipeline_timezone: str = Field(default="America/New_York", description="Timezone for pipeline schedule")
    pipeline_max_concurrency: int = Field(default=5, description="Max concurrent workers")
    pipeline_audit_batch_size: int = Field(default=3, description="P3a: symbols per gate audit batch (larger batches reduce repeated system prompt overhead)")
    pipeline_exec_batch_size: int = Field(default=3, description="P3b: symbols per execution plan batch")
    pipeline_llm_max_retries: int = Field(default=0, description="Max retries for LLM calls before skipping")
    
    # AI/LLM
    default_llm_model: str = Field(default="claude-opus-4.6", description="Default LLM model")
    default_llm_provider: str = Field(default="copilot", description="Default LLM provider (litellm, copilot, copilot-azure, mock)")

    # Per-phase max_tokens caps (output tokens).  Sized to expected output:
    #   P2 regime ~2-3K tokens, P3a verdict ~50 tokens/sym, P3b exec ~600 tokens/sym, P4 report ~4-6K tokens.
    llm_max_tokens_p2: int = Field(default=4096, description="Max output tokens for P2 regime analysis")
    llm_max_tokens_p3a: int = Field(default=4096, description="Max output tokens for P3a gate audit batch (increased for larger batch sizes)")
    llm_max_tokens_p3b: int = Field(default=4096, description="Max output tokens for P3b execution plan batch")
    llm_max_tokens_p4: int = Field(default=8192, description="Max output tokens for P4 portfolio briefing")
    
    # Limits
    default_max_symbols_per_user: int = Field(default=50, description="Default max symbols per user")
    
    # Logging
    log_format: str = Field(default="json", description="Log format: json or text")
    log_level: str = Field(default="INFO", description="Logging level")
    
    # LLM Progress Logging
    llm_progress_logging_enabled: bool = Field(default=True, description="Enable real-time LLM call progress logging")
    llm_progress_log_file: str = Field(default="logs/llm_calls.log", description="File path for LLM call logs")
    llm_progress_interval: float = Field(default=10.0, description="Seconds between LLM progress updates (console + pipeline.log)")
    llm_streaming_enabled: bool = Field(default=True, description="Enable streaming output for Copilot LLM calls (logs tokens as they arrive)")
    
    # Run Mode
    run_mode: str = Field(
        default="combined",
        description="Deployment mode: 'api-only' (API without scheduler), 'scheduler' (pipeline only), 'combined' (both)"
    )
    
    # Global symbols (fallback only — primary source is global_symbols DB table)
    global_symbols: list[str] = Field(
        default=["SPY", "QQQ", "DIA", "IWM", "TLT", "^VIX"],
        description="Fallback global symbols if database table is empty. VIX included for volatility regime context."
    )
    
    # Admin Seeding (for initial migration)
    admin_username: str = Field(default="admin", description="Initial admin username for seeding")
    admin_email: str = Field(default="admin@tradercat.com", description="Initial admin email for seeding")
    admin_max_symbols: int = Field(default=100, description="Initial admin max symbols limit")

    # JWT
    jwt_secret: str = Field(default="tradercat-jwt-secret-change-me", description="Secret key for JWT encoding")
    jwt_algorithm: str = Field(default="HS256", description="JWT algorithm")
    jwt_expire_minutes: int = Field(default=480, description="JWT token expiration in minutes (default 8h)")
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False
    )


# Global settings instance
settings = Settings()
