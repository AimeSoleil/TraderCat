"""014 — Add structured_json JSONB column to symbol_execution_plans.

Persists the P3 structured trade data (direction, quality, execution details,
legs, entry/stop/target, risk parameters) that was previously discarded before
DB insert. Used by the dashboard to display active positions without parsing
LLM markdown.

Revision ID: 014
Revises: 013
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "symbol_execution_plans",
        sa.Column("structured_json", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("symbol_execution_plans", "structured_json")
