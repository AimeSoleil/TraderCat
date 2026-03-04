"""016 — Widen execution plan free-text columns to Text.

Changes stop_loss, profit_target, and time_stop from VARCHAR to TEXT
on symbol_execution_plans to accommodate longer LLM-generated content.

Revision ID: 016
Revises: 015
"""
from alembic import op
import sqlalchemy as sa


revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "symbol_execution_plans",
        "stop_loss",
        type_=sa.Text(),
        existing_type=sa.String(200),
        existing_nullable=True,
    )
    op.alter_column(
        "symbol_execution_plans",
        "profit_target",
        type_=sa.Text(),
        existing_type=sa.String(200),
        existing_nullable=True,
    )
    op.alter_column(
        "symbol_execution_plans",
        "time_stop",
        type_=sa.Text(),
        existing_type=sa.String(100),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "symbol_execution_plans",
        "time_stop",
        type_=sa.String(100),
        existing_type=sa.Text(),
        existing_nullable=True,
    )
    op.alter_column(
        "symbol_execution_plans",
        "profit_target",
        type_=sa.String(200),
        existing_type=sa.Text(),
        existing_nullable=True,
    )
    op.alter_column(
        "symbol_execution_plans",
        "stop_loss",
        type_=sa.String(200),
        existing_type=sa.Text(),
        existing_nullable=True,
    )
