"""012 — Pipeline v2: Replace global_reports/user_reports with 3 dedicated tables.

New tables:
  - macro_regime_contexts  (P2 output — one per run_date)
  - symbol_execution_plans (P3 output — one per run_date×symbol)
  - user_briefings         (P4 output — one per user_id×run_date)

Dropped tables:
  - global_reports
  - user_reports

Revision ID: 012
Revises: 011
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Create macro_regime_contexts ---
    op.create_table(
        "macro_regime_contexts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_date", sa.Date(), nullable=False),
        sa.Column("regime_label", sa.String(50), nullable=True),
        sa.Column("regime_score", sa.Float(), nullable=True),
        sa.Column("content_md", sa.Text(), nullable=False),
        sa.Column("downstream_filters", postgresql.JSONB(), nullable=True),
        sa.Column("model_used", sa.String(100), nullable=True),
        sa.Column("identity_used", sa.String(50), nullable=True),
        sa.Column("input_context", postgresql.JSONB(), nullable=True),
        sa.Column("pipeline_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_macro_regime_run_date", "macro_regime_contexts", ["run_date"], unique=True)

    # --- Create symbol_execution_plans ---
    op.create_table(
        "symbol_execution_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_date", sa.Date(), nullable=False),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("verdict", sa.String(20), nullable=True),
        sa.Column("setup_quality", sa.String(10), nullable=True),
        sa.Column("content_md", sa.Text(), nullable=False),
        sa.Column("model_used", sa.String(100), nullable=True),
        sa.Column("identity_used", sa.String(50), nullable=True),
        sa.Column("input_context", postgresql.JSONB(), nullable=True),
        sa.Column("pipeline_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_exec_plan_run_date", "symbol_execution_plans", ["run_date"])
    op.create_index("ix_exec_plan_symbol", "symbol_execution_plans", ["symbol"])
    op.create_index("ix_exec_plan_run_date_symbol", "symbol_execution_plans", ["run_date", "symbol"])
    op.create_unique_constraint(
        "uq_exec_plan_run_date_symbol",
        "symbol_execution_plans",
        ["run_date", "symbol"],
    )

    # --- Create user_briefings ---
    op.create_table(
        "user_briefings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("run_date", sa.Date(), nullable=False),
        sa.Column("content_md", sa.Text(), nullable=False),
        sa.Column("model_used", sa.String(100), nullable=True),
        sa.Column("identity_used", sa.String(50), nullable=True),
        sa.Column("input_context", postgresql.JSONB(), nullable=True),
        sa.Column("pipeline_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_user_briefing_user_id", "user_briefings", ["user_id"])
    op.create_index("ix_user_briefing_run_date", "user_briefings", ["run_date"])
    op.create_index("ix_user_briefing_user_run_date", "user_briefings", ["user_id", "run_date"])
    op.create_unique_constraint(
        "uq_user_briefing_user_run_date",
        "user_briefings",
        ["user_id", "run_date"],
    )

    # --- Drop old tables ---
    op.drop_table("user_reports")
    op.drop_table("global_reports")


def downgrade() -> None:
    # --- Recreate global_reports ---
    op.create_table(
        "global_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_date", sa.Date(), nullable=False),
        sa.Column("symbol", sa.String(20), nullable=True),
        sa.Column("report_type", sa.String(50), nullable=False),
        sa.Column("content_md", sa.Text(), nullable=False),
        sa.Column("model_used", sa.String(100), nullable=True),
        sa.Column("identity_used", sa.String(50), nullable=True),
        sa.Column("input_context", postgresql.JSONB(), nullable=True),
        sa.Column("pipeline_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_global_report_run_date", "global_reports", ["run_date"])

    # --- Recreate user_reports ---
    op.create_table(
        "user_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("run_date", sa.Date(), nullable=False),
        sa.Column("report_type", sa.String(50), nullable=False),
        sa.Column("content_md", sa.Text(), nullable=False),
        sa.Column("model_used", sa.String(100), nullable=True),
        sa.Column("identity_used", sa.String(50), nullable=True),
        sa.Column("input_context", postgresql.JSONB(), nullable=True),
        sa.Column("pipeline_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_user_report_user_id", "user_reports", ["user_id"])
    op.create_index("ix_user_report_run_date", "user_reports", ["run_date"])

    # --- Drop new tables ---
    op.drop_table("user_briefings")
    op.drop_table("symbol_execution_plans")
    op.drop_table("macro_regime_contexts")
