"""Rename api_keys table to personal_access_tokens

Revision ID: 010
Revises: 009
Create Date: 2025-07-24 12:00:00.000000

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Rename table
    op.rename_table("api_keys", "personal_access_tokens")

    # Rename index (PostgreSQL auto-renames PK constraints but not custom indexes)
    op.execute(
        "ALTER INDEX IF EXISTS ix_api_keys_user_id RENAME TO ix_personal_access_tokens_user_id"
    )


def downgrade() -> None:
    op.execute(
        "ALTER INDEX IF EXISTS ix_personal_access_tokens_user_id RENAME TO ix_api_keys_user_id"
    )
    op.rename_table("personal_access_tokens", "api_keys")
