"""015 — Create symbol_verdicts table and restructure symbol_execution_plans.

Creates a new `symbol_verdicts` table with fixed schema for P3a gate audit output.
Restructures `symbol_execution_plans` to a fixed schema for P3b execution plans.

Both tables store one record per (run_date, symbol) with typed, queryable columns
plus a raw_json column preserving the full LLM output.

Revision ID: 015
Revises: 014
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ══════════════════════════════════════════════════════════
    # 1. Create symbol_verdicts table
    # ══════════════════════════════════════════════════════════
    op.create_table(
        "symbol_verdicts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_date", sa.Date(), nullable=False, index=True),
        sa.Column("symbol", sa.String(20), nullable=False, index=True),

        # Core verdict
        sa.Column("direction", sa.String(20), nullable=False),
        sa.Column("quality", sa.String(10), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("rr_estimate", sa.String(20), nullable=True),
        sa.Column("setup_type", sa.String(30), nullable=True),

        # Confluence
        sa.Column("confluence", sa.String(200), nullable=True),
        sa.Column("confluence_count", sa.Integer(), nullable=True),

        # Historical continuity
        sa.Column("historical_trend", sa.String(20), nullable=True),

        # Gate results
        sa.Column("gates", sa.String(60), nullable=True),
        sa.Column("rejection_reason", sa.String(500), nullable=True),

        # Trend (Gate 3)
        sa.Column("trend_adx", sa.Float(), nullable=True),
        sa.Column("trend_ema_fast", sa.Float(), nullable=True),
        sa.Column("trend_ema_slow", sa.Float(), nullable=True),
        sa.Column("trend_ema_spread_pct", sa.Float(), nullable=True),
        sa.Column("trend_pct_b", sa.Float(), nullable=True),

        # Momentum (Gate 4)
        sa.Column("momentum_rsi", sa.Float(), nullable=True),
        sa.Column("momentum_macd_hist", sa.Float(), nullable=True),
        sa.Column("momentum_mom_score", sa.Float(), nullable=True),

        # Volume (Gate 5)
        sa.Column("volume_rel", sa.Float(), nullable=True),
        sa.Column("volume_zscore", sa.Float(), nullable=True),
        sa.Column("volume_classification", sa.String(30), nullable=True),

        # Volatility
        sa.Column("volatility_atr_pct", sa.Float(), nullable=True),
        sa.Column("volatility_bandwidth", sa.Float(), nullable=True),
        sa.Column("volatility_squeeze", sa.Boolean(), nullable=True),

        # Key levels
        sa.Column("key_level_support", sa.Float(), nullable=True),
        sa.Column("key_level_resistance", sa.Float(), nullable=True),

        # Strategy recommendation
        sa.Column("recommended_strategy_type", sa.String(50), nullable=True),

        # Raw JSON
        sa.Column("raw_json", postgresql.JSONB(), nullable=True),

        # Metadata
        sa.Column("model_used", sa.String(100), nullable=True),
        sa.Column("identity_used", sa.String(50), nullable=True),
        sa.Column("pipeline_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),

        # Constraints
        sa.UniqueConstraint("run_date", "symbol", name="uq_verdict_run_date_symbol"),
    )
    op.create_index("ix_verdict_run_date_symbol", "symbol_verdicts", ["run_date", "symbol"])
    op.create_index("ix_verdict_direction", "symbol_verdicts", ["direction"])
    op.create_index("ix_verdict_quality", "symbol_verdicts", ["quality"])

    # ══════════════════════════════════════════════════════════
    # 2. Restructure symbol_execution_plans — add new columns
    # ══════════════════════════════════════════════════════════

    # Add new fixed-schema columns
    op.add_column("symbol_execution_plans", sa.Column("structure", sa.String(50), nullable=True))
    op.add_column("symbol_execution_plans", sa.Column("direction", sa.String(10), nullable=True))
    op.add_column("symbol_execution_plans", sa.Column("thesis", sa.Text(), nullable=True))
    op.add_column("symbol_execution_plans", sa.Column("rationale", sa.Text(), nullable=True))
    op.add_column("symbol_execution_plans", sa.Column("legs", postgresql.JSONB(), nullable=True))
    op.add_column("symbol_execution_plans", sa.Column("entry_trigger", sa.Text(), nullable=True))
    op.add_column("symbol_execution_plans", sa.Column("stop_loss", sa.String(200), nullable=True))
    op.add_column("symbol_execution_plans", sa.Column("profit_target", sa.String(200), nullable=True))
    op.add_column("symbol_execution_plans", sa.Column("time_stop", sa.String(100), nullable=True))
    op.add_column("symbol_execution_plans", sa.Column("max_loss", sa.String(50), nullable=True))
    op.add_column("symbol_execution_plans", sa.Column("max_profit", sa.String(50), nullable=True))
    op.add_column("symbol_execution_plans", sa.Column("breakeven", sa.String(100), nullable=True))
    op.add_column("symbol_execution_plans", sa.Column("rr_ratio", sa.String(20), nullable=True))
    op.add_column("symbol_execution_plans", sa.Column("allocation", sa.String(100), nullable=True))
    op.add_column("symbol_execution_plans", sa.Column("dte", sa.Integer(), nullable=True))
    op.add_column("symbol_execution_plans", sa.Column("raw_json", postgresql.JSONB(), nullable=True))

    # Make content_md nullable (execution plans may not have rendered markdown)
    op.alter_column("symbol_execution_plans", "content_md", nullable=True)

    # Drop old columns that are now in symbol_verdicts or replaced
    op.drop_column("symbol_execution_plans", "verdict")
    op.drop_column("symbol_execution_plans", "setup_quality")
    op.drop_column("symbol_execution_plans", "input_context")
    op.drop_column("symbol_execution_plans", "structured_json")


def downgrade() -> None:
    # Restore old columns on symbol_execution_plans
    op.add_column("symbol_execution_plans", sa.Column("verdict", sa.String(20), nullable=True))
    op.add_column("symbol_execution_plans", sa.Column("setup_quality", sa.String(10), nullable=True))
    op.add_column("symbol_execution_plans", sa.Column("input_context", postgresql.JSONB(), nullable=True))
    op.add_column("symbol_execution_plans", sa.Column("structured_json", postgresql.JSONB(), nullable=True))

    # Make content_md non-nullable again
    op.alter_column("symbol_execution_plans", "content_md", nullable=False)

    # Drop new columns from symbol_execution_plans
    op.drop_column("symbol_execution_plans", "raw_json")
    op.drop_column("symbol_execution_plans", "dte")
    op.drop_column("symbol_execution_plans", "allocation")
    op.drop_column("symbol_execution_plans", "rr_ratio")
    op.drop_column("symbol_execution_plans", "breakeven")
    op.drop_column("symbol_execution_plans", "max_profit")
    op.drop_column("symbol_execution_plans", "max_loss")
    op.drop_column("symbol_execution_plans", "time_stop")
    op.drop_column("symbol_execution_plans", "profit_target")
    op.drop_column("symbol_execution_plans", "stop_loss")
    op.drop_column("symbol_execution_plans", "entry_trigger")
    op.drop_column("symbol_execution_plans", "legs")
    op.drop_column("symbol_execution_plans", "rationale")
    op.drop_column("symbol_execution_plans", "thesis")
    op.drop_column("symbol_execution_plans", "direction")
    op.drop_column("symbol_execution_plans", "structure")

    # Drop symbol_verdicts table
    op.drop_index("ix_verdict_quality", "symbol_verdicts")
    op.drop_index("ix_verdict_direction", "symbol_verdicts")
    op.drop_index("ix_verdict_run_date_symbol", "symbol_verdicts")
    op.drop_table("symbol_verdicts")
