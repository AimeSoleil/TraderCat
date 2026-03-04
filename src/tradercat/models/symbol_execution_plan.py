"""Symbol execution plan models — P3b pipeline output.

Stores per-symbol options execution plans produced by OptionsStrategistRole.
One record per (run_date, symbol) pair with a fixed, structured schema.

The execution plan captures the complete trade construction: structure, legs,
entry/exit rules, risk parameters, allocation, and Greeks estimates.
"""
from datetime import datetime, date, timezone
from uuid import uuid4
from sqlalchemy import (
    Column, String, Text, Float, Integer, Date, DateTime,
    Index, UniqueConstraint, JSON,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB

from tradercat.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class SymbolExecutionPlan(Base):
    """
    Symbol execution plan — P3b output.

    Fixed-schema table storing the daily options execution plan for each symbol.
    Only populated for symbols that pass the P3a gate audit (approved symbols).
    Columns are typed and queryable; raw_json preserves the full LLM output.
    """
    __tablename__ = "symbol_execution_plans"
    __table_args__ = (
        UniqueConstraint("run_date", "symbol", name="uq_exec_plan_run_date_symbol"),
        Index("ix_exec_plan_run_date_symbol", "run_date", "symbol"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    run_date = Column(Date, nullable=False, index=True)
    symbol = Column(String(20), nullable=False, index=True)

    # ── Trade Structure ──
    structure = Column(String(50), nullable=True)      # e.g. "Bull Call Spread", "Iron Condor"
    direction = Column(String(10), nullable=True)       # "credit" / "debit"
    thesis = Column(Text, nullable=True)                # 1-2 sentence trade thesis
    rationale = Column(Text, nullable=True)             # Why this structure fits

    # ── Legs (JSON array — [{type, strike, exp, action, delta, premium}]) ──
    legs = Column(
        JSONB().with_variant(JSON, "sqlite"),
        nullable=True,
    )

    # ── Entry Trigger ──
    entry_trigger = Column(Text, nullable=True)         # e.g. "Close above $193 on 1.5x avg volume"

    # ── Risk Parameters ──
    stop_loss = Column(String(200), nullable=True)      # e.g. "$3.10 (1.5xATR) or 100% of net debit"
    profit_target = Column(String(200), nullable=True)  # e.g. "75% of max profit ($5.63)"
    time_stop = Column(String(100), nullable=True)      # e.g. "Close by 21 DTE"
    max_loss = Column(String(50), nullable=True)        # e.g. "$3.10 / contract"
    max_profit = Column(String(50), nullable=True)      # e.g. "$6.90 / contract"
    breakeven = Column(String(100), nullable=True)      # e.g. "$193.10" or multiple values
    rr_ratio = Column(String(20), nullable=True)        # e.g. "2.2:1"

    # ── Allocation & Sizing ──
    allocation = Column(String(100), nullable=True)     # e.g. "15% ($300)"
    dte = Column(Integer, nullable=True)                # Days to expiration

    # ── Content (backward-compatible rendered markdown) ──
    content_md = Column(Text, nullable=True)            # Rendered markdown for frontend display

    # ── Raw JSON (complete LLM output for reference) ──
    raw_json = Column(
        JSONB().with_variant(JSON, "sqlite"),
        nullable=True,
    )

    # ── Metadata ──
    model_used = Column(String(100), nullable=True)
    identity_used = Column(String(50), nullable=True)
    pipeline_run_id = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)
