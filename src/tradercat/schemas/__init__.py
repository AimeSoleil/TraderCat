"""Pydantic schemas package."""
from tradercat.schemas.user import (
    UserCreate,
    UserUpdate,
    UserResponse,
    UserWithTokens,
    UserWithKeys,  # backward-compatible alias
    TokenResponse,
    TokenCreate,
    TokenCreated,
    ApiKeyResponse,  # backward-compatible alias
    ApiKeyCreate,  # backward-compatible alias
    ApiKeyCreated,  # backward-compatible alias
)
from tradercat.schemas.symbol import (
    WatchlistItemCreate,
    WatchlistItemResponse,
    WatchlistItemList,
)
from tradercat.schemas.signal import (
    SignalResponse,
    SignalList,
    SignalQuery,
)
from tradercat.schemas.report import (
    GlobalReportResponse,
    GlobalReportDetail,
    GlobalReportList,
    UserReportResponse,
    UserReportDetail,
    UserReportList,
)
from tradercat.schemas.strategy import (
    StrategyResponse,
    StrategyWithPresets,
    StrategyPresetResponse,
    StrategyPresetCreate,
    StrategyPresetUpdate,
    StrategyPresetBatchUpdate,
    StrategyActivePresetUpdate,
    StrategyListResponse,
    StrategyPresetListResponse,
)
from tradercat.schemas.llm_token import (
    LlmTokenCreate,
    LlmTokenUpdate,
    LlmTokenResponse,
    LlmTokenListResponse,
)

__all__ = [
    "UserCreate",
    "UserUpdate",
    "UserResponse",
    "UserWithTokens",
    "UserWithKeys",
    "TokenResponse",
    "TokenCreate",
    "TokenCreated",
    "ApiKeyResponse",
    "ApiKeyCreate",
    "ApiKeyCreated",
    "WatchlistItemCreate",
    "WatchlistItemResponse",
    "WatchlistItemList",
    "SignalResponse",
    "SignalList",
    "SignalQuery",
    "GlobalReportResponse",
    "GlobalReportDetail",
    "GlobalReportList",
    "UserReportResponse",
    "UserReportDetail",
    "UserReportList",
    "StrategyResponse",
    "StrategyWithPresets",
    "StrategyPresetResponse",
    "StrategyPresetCreate",
    "StrategyPresetUpdate",
    "StrategyPresetBatchUpdate",
    "StrategyActivePresetUpdate",
    "StrategyListResponse",
    "StrategyPresetListResponse",
    "LlmTokenCreate",
    "LlmTokenUpdate",
    "LlmTokenResponse",
    "LlmTokenListResponse",
]
