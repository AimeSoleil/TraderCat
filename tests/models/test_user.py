"""Tests for user models and API key authentication."""
import pytest
from sqlalchemy import select

from tradercat.models import User, ApiKey


@pytest.mark.asyncio
async def test_create_user(db_session):
    """Test creating a user."""
    user = User(
        username="newuser",
        email="newuser@example.com",
        role="user",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    
    assert user.id is not None
    assert user.username == "newuser"
    assert user.email == "newuser@example.com"
    assert user.role == "user"
    assert user.is_active is True
    assert user.max_symbols == 50


@pytest.mark.asyncio
async def test_api_key_generation():
    """Test API key generation and hashing."""
    plaintext, key_hash = ApiKey.generate_key()
    
    assert plaintext.startswith("tc_")
    assert len(plaintext) > 20
    assert len(key_hash) == 64  # SHA-256 hex digest
    
    # Verify hash matches
    assert ApiKey.hash_key(plaintext) == key_hash


@pytest.mark.asyncio
async def test_api_key_prefix():
    """Test API key prefix extraction."""
    plaintext = "tc_test123456789"
    prefix = ApiKey.get_key_prefix(plaintext)
    
    assert prefix == "tc_test12345"
    assert len(prefix) == 12


@pytest.mark.asyncio
async def test_user_api_key_relationship(db_session, test_user):
    """Test user-apikey relationship."""
    # Create API key for user
    plaintext, key_hash = ApiKey.generate_key()
    api_key = ApiKey(
        user_id=test_user.id,
        key_hash=key_hash,
        key_prefix=ApiKey.get_key_prefix(plaintext),
        name="test_key",
    )
    db_session.add(api_key)
    await db_session.commit()
    
    # Query user and check relationship
    result = await db_session.execute(
        select(User).where(User.id == test_user.id)
    )
    user = result.scalars().first()
    
    # Note: In SQLite async, relationships might not be auto-loaded
    # So we query explicitly
    result = await db_session.execute(
        select(ApiKey).where(ApiKey.user_id == user.id)
    )
    keys = result.scalars().all()
    
    assert len(keys) == 1
    assert keys[0].name == "test_key"
    assert keys[0].user_id == user.id
