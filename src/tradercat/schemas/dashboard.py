"""Dashboard schemas for API response.

Position data from symbol_verdicts + symbol_execution_plans,
combined with briefing and regime context for the dashboard view.
"""
from datetime import date
from uuid import UUID
from pydantic import BaseModel
from typing import Any


class DashboardPositionItem(BaseModel):
    """A single position/trade from P3 structured data."""
    id: UUID
    symbol: str
    run_date: date
    verdict: str | None          # buy, sell, hold, watchlist, reject
    setup_quality: str | None    # A+, A, B+, B, C, REJECT
    direction: str | None        # LONG, SHORT, NEUTRAL
    setup_type: str | None       # Trend Breakout, Reversal, etc.
    confluence: str | None       # e.g. "BBrk+Mom"
    rr_estimate: str | None      # e.g. "2.5:1"
    rejection_reason: str | None

    # Execution details
    structure: str | None        # Bull Call Spread, Iron Condor, etc.
    legs: list[dict[str, Any]] | None  # [{ action, type, strike, exp, delta, premium }]
    entry_price: str | None
    stop_loss: str | None
    profit_target: str | None
    time_stop: str | None
    max_loss: str | None
    max_profit: str | None
    allocation: str | None
    breakeven: str | None
    thesis: str | None

    rank: int
    has_structured_data: bool    # True if P3 returned execution details

    model_config = {"from_attributes": True}


class DashboardResponse(BaseModel):
    """Dashboard positions response with context."""
    positions: list[DashboardPositionItem]
    run_date: str | None
    briefing_id: str | None
    regime_label: str | None
    regime_score: float | None
    total_positions: int
    signal_count: int = 0
    available_dates: list[str]
