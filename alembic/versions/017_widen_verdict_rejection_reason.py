"""017 — Widen rejection_reason column to VARCHAR(2000).

Increases rejection_reason on symbol_verdicts from VARCHAR(500) to VARCHAR(2000)
to accommodate longer LLM-generated rejection explanations.

Revision ID: 017
Revises: 016
"""
from alembic import op
import sqlalchemy as sa


revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "symbol_verdicts",
        "rejection_reason",
        type_=sa.String(2000),
        existing_type=sa.String(500),
        existing_nullable=True,
    )


def downgrade() -> None:
    # WARNING: Downgrading will truncate any rejection_reason > 500 chars
    op.alter_column(
        "symbol_verdicts",
        "rejection_reason",
        type_=sa.String(500),
        existing_type=sa.String(2000),
        existing_nullable=True,
    )
