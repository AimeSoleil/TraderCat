"""Seed initial admin user

Revision ID: 002
Revises: 001
Create Date: 2026-02-11 09:35:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from datetime import datetime
from uuid import uuid4
import hashlib
import secrets
import os

# revision identifiers, used by Alembic.
revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None


def generate_api_key() -> tuple[str, str, str]:
    """
    Generate a new API key.
    
    Returns:
        tuple: (plaintext_key, key_hash, key_prefix)
    """
    plaintext = "tc_" + secrets.token_urlsafe(24)
    key_hash = hashlib.sha256(plaintext.encode()).hexdigest()
    key_prefix = plaintext[:12]
    return plaintext, key_hash, key_prefix


def upgrade() -> None:
    # Get admin details from environment variables or use defaults
    admin_username = os.getenv("ADMIN_USERNAME", "admin")
    admin_email = os.getenv("ADMIN_EMAIL", "admin@tradercat.com")
    admin_max_symbols = int(os.getenv("ADMIN_MAX_SYMBOLS", "100"))
    
    # Check if admin already exists
    connection = op.get_bind()
    result = connection.execute(
        sa.text("SELECT id FROM users WHERE username = :username"),
        {"username": admin_username}
    )
    existing_admin = result.fetchone()
    
    if existing_admin:
        print(f"ℹ️  Admin user '{admin_username}' already exists. Skipping seed.")
        return
    
    # Generate admin user ID
    admin_id = uuid4()
    now = datetime.utcnow()
    
    # Insert admin user
    connection.execute(
        sa.text("""
            INSERT INTO users (id, username, email, role, is_active, max_symbols, created_at, updated_at)
            VALUES (:id, :username, :email, :role, :is_active, :max_symbols, :created_at, :updated_at)
        """),
        {
            "id": admin_id,
            "username": admin_username,
            "email": admin_email,
            "role": "admin",
            "is_active": True,
            "max_symbols": admin_max_symbols,
            "created_at": now,
            "updated_at": now,
        }
    )
    
    # Generate API key for admin
    plaintext_key, key_hash, key_prefix = generate_api_key()
    api_key_id = uuid4()
    
    connection.execute(
        sa.text("""
            INSERT INTO api_keys (id, user_id, key_hash, key_prefix, name, is_active, created_at)
            VALUES (:id, :user_id, :key_hash, :key_prefix, :name, :is_active, :created_at)
        """),
        {
            "id": api_key_id,
            "user_id": admin_id,
            "key_hash": key_hash,
            "key_prefix": key_prefix,
            "name": "Initial Admin Key",
            "is_active": True,
            "created_at": now,
        }
    )
    
    # Print the API key (only time it's shown in plaintext)
    print("\n" + "="*80)
    print("🎉 INITIAL ADMIN USER CREATED SUCCESSFULLY!")
    print("="*80)
    print(f"Username: {admin_username}")
    print(f"Email:    {admin_email}")
    print(f"Role:     admin")
    print(f"Max Symbols: {admin_max_symbols}")
    print(f"\n🔑 API KEY (save this, it won't be shown again):")
    print(f"   {plaintext_key}")
    print("="*80)
    print("\nUse this API key in the X-API-Key header to authenticate API requests.")
    print("Example: curl -H 'X-API-Key: {key}' http://localhost:8000/api/v1/users\n")


def downgrade() -> None:
    # Remove the seeded admin user (and cascade will remove API key)
    admin_username = os.getenv("ADMIN_USERNAME", "admin")
    connection = op.get_bind()
    
    # Get admin user ID
    result = connection.execute(
        sa.text("SELECT id FROM users WHERE username = :username"),
        {"username": admin_username}
    )
    admin_user = result.fetchone()
    
    if admin_user:
        # Delete API keys first (explicit for clarity, though CASCADE would handle it)
        connection.execute(
            sa.text("DELETE FROM api_keys WHERE user_id = :user_id"),
            {"user_id": admin_user[0]}
        )
        
        # Delete admin user
        connection.execute(
            sa.text("DELETE FROM users WHERE id = :id"),
            {"id": admin_user[0]}
        )
        
        print(f"✅ Removed admin user '{admin_username}' and associated API keys.")
