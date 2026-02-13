"""Add unique constraint on signal_records (run_date, symbol, strategy)

Revision ID: 006
Revises: 005
Create Date: 2026-02-13 18:00:00.000000

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = '006'
down_revision = '005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Deduplicate existing rows before adding the constraint.
    # For each (run_date, symbol, strategy) group, keep only the latest row.
    op.execute("""
        DELETE FROM signal_records
        WHERE id NOT IN (
            SELECT DISTINCT ON (run_date, symbol, strategy) id
            FROM signal_records
            ORDER BY run_date, symbol, strategy, created_at DESC
        )
    """)

    op.create_unique_constraint(
        "uq_signal_run_date_symbol_strategy",
        "signal_records",
        ["run_date", "symbol", "strategy"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_signal_run_date_symbol_strategy",
        "signal_records",
        type_="unique",
    )
