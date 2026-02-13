"""Rename watchlist_items.company_name to description

Revision ID: 004
Revises: 003
Create Date: 2026-02-13 10:00:00.000000

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = '004'
down_revision = '003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        'watchlist_items',
        'company_name',
        new_column_name='description',
    )


def downgrade() -> None:
    op.alter_column(
        'watchlist_items',
        'description',
        new_column_name='company_name',
    )
