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
    api_description: str = "Multi-tenant trading signal and report generation API"
    
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
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False
    )


# Global settings instance
settings = Settings()
