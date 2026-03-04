"""Symbol verdict models — P3a pipeline output.

Stores per-symbol trading verdicts from the gate audit phase.
One record per (run_date, symbol) pair with a fixed, structured schema.

The verdict captures the directional view, confidence, trend/momentum/volatility
assessment, key levels, and recommended strategy type for a single symbol.
"""
from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import (
    Column, String, Text, Float, Integer, Date, DateTime, Boolean,
    Index, UniqueConstraint, JSON,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB

from tradercat.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class SymbolVerdict(Base):
    """
    Symbol verdict — P3a gate audit output.

    Fixed-schema table storing the daily trading verdict for each symbol.
    Columns are typed and queryable; raw_json preserves the full LLM output.
    """
    __tablename__ = "symbol_verdicts"
    __table_args__ = (
        UniqueConstraint("run_date", "symbol", name="uq_verdict_run_date_symbol"),
        Index("ix_verdict_run_date_symbol", "run_date", "symbol"),
        Index("ix_verdict_direction", "direction"),
        Index("ix_verdict_quality", "quality"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    run_date = Column(Date, nullable=False, index=True)
    symbol = Column(String(20), nullable=False, index=True)

    # ── Core Verdict ──
    direction = Column(String(20), nullable=False)    # LONG / SHORT / NEUTRAL
    quality = Column(String(10), nullable=False)       # A+ / A / B+ / B / C / REJECT
    confidence = Column(Float, nullable=True)          # 0.0 - 1.0
    rr_estimate = Column(String(20), nullable=True)    # e.g. "2.5:1"
    setup_type = Column(String(30), nullable=True)     # Breakout / Reversal / Squeeze / Pattern / Continuation

    # ── Confluence ──
    confluence = Column(String(200), nullable=True)        # e.g. "BollingerBreakout + MomentumTrend"
    confluence_count = Column(Integer, nullable=True)      # number of confirming strategies

    # ── Historical Continuity (Gate 0) ──
    historical_trend = Column(String(20), nullable=True)   # CONSISTENT / REVERSING / MIXED

    # ── Gate Results ──
    gates = Column(String(60), nullable=True)              # e.g. "0:P|1:P|2:P|3:P|4:P|5:P|6:P"
    rejection_reason = Column(String(500), nullable=True)  # null if approved

    # ── Trend (Gate 3) ──
    trend_adx = Column(Float, nullable=True)
    trend_ema_fast = Column(Float, nullable=True)
    trend_ema_slow = Column(Float, nullable=True)
    trend_ema_spread_pct = Column(Float, nullable=True)
    trend_pct_b = Column(Float, nullable=True)

    # ── Momentum (Gate 4) ──
    momentum_rsi = Column(Float, nullable=True)
    momentum_macd_hist = Column(Float, nullable=True)
    momentum_mom_score = Column(Float, nullable=True)

    # ── Volume (Gate 5) ──
    volume_rel = Column(Float, nullable=True)
    volume_zscore = Column(Float, nullable=True)
    volume_classification = Column(String(30), nullable=True)  # Institutional / Above avg / Normal / Ghost

    # ── Volatility ──
    volatility_atr_pct = Column(Float, nullable=True)
    volatility_bandwidth = Column(Float, nullable=True)
    volatility_squeeze = Column(Boolean, nullable=True)

    # ── Key Levels ──
    key_level_support = Column(Float, nullable=True)
    key_level_resistance = Column(Float, nullable=True)

    # ── Strategy Recommendation ──
    recommended_strategy_type = Column(String(50), nullable=True)  # e.g. "bull_call_spread"

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
