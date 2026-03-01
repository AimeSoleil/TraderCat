"""Rename api_keys table to personal_access_tokens

Revision ID: 011
Revises: 010
Create Date: 2025-07-24 12:00:00.000000

"""
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    tables = inspector.get_table_names()

    if "api_keys" in tables and "personal_access_tokens" not in tables:
        # Normal path: rename the table
        op.rename_table("api_keys", "personal_access_tokens")
    # else: already renamed or personal_access_tokens already exists — skip

    # Rename index (PostgreSQL auto-renames PK constraints but not custom indexes)
    op.execute(
        "ALTER INDEX IF EXISTS ix_api_keys_user_id RENAME TO ix_personal_access_tokens_user_id"
    )


def downgrade() -> None:
    op.execute(
        "ALTER INDEX IF EXISTS ix_personal_access_tokens_user_id RENAME TO ix_api_keys_user_id"
    )
    op.rename_table("personal_access_tokens", "api_keys")
