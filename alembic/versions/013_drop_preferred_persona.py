"""013 — Drop preferred_persona column from users table.

Identity is now internal/functional per pipeline phase, not user-configurable.

Revision ID: 013
Revises: 012
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("users", "preferred_persona")


def downgrade() -> None:
    op.add_column(
        "users",
        sa.Column("preferred_persona", sa.String(50), nullable=True),
    )
