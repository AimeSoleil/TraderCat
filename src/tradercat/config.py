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

* 🔐 **API Key Authentication** - Secure access with SHA-256 hashed keys
* 👥 **Multi-Tenant** - User-level watchlists and reports
* 📊 **8 Trading Strategies** - Technical analysis with customizable parameters
* 🤖 **AI Reports** - LLM-powered market analysis (GPT-4)
* 📅 **Scheduled Pipeline** - Automatic nightly signal generation
* 🎯 **Smart Deduplication** - Global + user-specific signals

### Authentication

All endpoints (except `/` and `/api/admin/system/health`) require API key authentication:

```
X-API-Key: tc_your_api_key_here
```

Admin endpoints require admin-level API keys.

### Getting Started

1. **Admin creates user**: `POST /api/v1/users` (returns API key)
2. **Add watchlist symbols**: `POST /api/v1/watchlist`
3. **View signals**: `GET /api/v1/signals`
4. **Read reports**: `GET /api/v1/reports`

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
    
    # AI/LLM
    tradercat_ai_token: str = Field(default="", description="GitHub Copilot SDK token")
    default_llm_model: str = Field(default="gpt-4o", description="Default LLM model")
    default_persona: str = Field(default="wyckoff", description="Default analyst persona")
    
    # Limits
    default_max_symbols_per_user: int = Field(default=50, description="Default max symbols per user")
    
    # Logging
    log_format: str = Field(default="json", description="Log format: json or text")
    log_level: str = Field(default="INFO", description="Logging level")
    
    # Run Mode
    run_mode: str = Field(
        default="combined",
        description="Deployment mode: 'api-only' (API without scheduler), 'scheduler' (pipeline only), 'combined' (both)"
    )
    
    # Global symbols (predefined for signal generation)
    global_symbols: list[str] = Field(
        default=["SPY", "QQQ", "DIA", "IWM", "TLT", "XLK", "XLF", "XLY", "XLV", "XLE", "XLI", "XLP"],
        description="Predefined global symbols for signal generation"
    )
    
    # Admin Seeding (for initial migration)
    admin_username: str = Field(default="admin", description="Initial admin username for seeding")
    admin_email: str = Field(default="admin@tradercat.local", description="Initial admin email for seeding")
    admin_max_symbols: int = Field(default=100, description="Initial admin max symbols limit")
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False
    )


# Global settings instance
settings = Settings()
