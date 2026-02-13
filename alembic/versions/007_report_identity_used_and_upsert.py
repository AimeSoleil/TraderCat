"""Rename persona_used to identity_used + add upsert constraints on reports

Revision ID: 007
Revises: 006
Create Date: 2026-02-13 19:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '007'
down_revision = '006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. Rename persona_used → identity_used ──
    op.alter_column(
        "global_reports", "persona_used",
        new_column_name="identity_used",
    )
    op.alter_column(
        "user_reports", "persona_used",
        new_column_name="identity_used",
    )

    # ── 2. Deduplicate global_reports before adding unique index ──
    # For rows WITH symbol: keep latest per (run_date, report_type, symbol)
    op.execute("""
        DELETE FROM global_reports
        WHERE id NOT IN (
            SELECT DISTINCT ON (run_date, report_type, COALESCE(symbol, '')) id
            FROM global_reports
            ORDER BY run_date, report_type, COALESCE(symbol, ''), created_at DESC
        )
    """)

    # Functional unique index handling NULL symbol via COALESCE
    op.execute("""
        CREATE UNIQUE INDEX uq_global_report_composite
        ON global_reports (run_date, report_type, COALESCE(symbol, ''))
    """)

    # ── 3. Deduplicate user_reports before adding unique constraint ──
    op.execute("""
        DELETE FROM user_reports
        WHERE id NOT IN (
            SELECT DISTINCT ON (user_id, run_date, report_type) id
            FROM user_reports
            ORDER BY user_id, run_date, report_type, created_at DESC
        )
    """)

    op.create_unique_constraint(
        "uq_user_report_user_run_date_type",
        "user_reports",
        ["user_id", "run_date", "report_type"],
    )


def downgrade() -> None:
    # Drop constraints
    op.drop_constraint("uq_user_report_user_run_date_type", "user_reports", type_="unique")
    op.execute("DROP INDEX IF EXISTS uq_global_report_composite")

    # Rename back
    op.alter_column(
        "global_reports", "identity_used",
        new_column_name="persona_used",
    )
    op.alter_column(
        "user_reports", "identity_used",
        new_column_name="persona_used",
    )
