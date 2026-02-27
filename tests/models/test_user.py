"""Tests for user models and personal access token authentication."""
import pytest
from sqlalchemy import select

from tradercat.models import User, PersonalAccessToken


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
async def test_token_generation():
    """Test personal access token generation and hashing."""
    plaintext, key_hash = PersonalAccessToken.generate_key()
    
    assert plaintext.startswith("tc_")
    assert len(plaintext) > 20
    assert len(key_hash) == 64  # SHA-256 hex digest
    
    # Verify hash matches
    assert PersonalAccessToken.hash_key(plaintext) == key_hash


@pytest.mark.asyncio
async def test_token_prefix():
    """Test token prefix extraction."""
    plaintext = "tc_test123456789"
    prefix = PersonalAccessToken.get_key_prefix(plaintext)
    
    assert prefix == "tc_test12345"
    assert len(prefix) == 12


@pytest.mark.asyncio
async def test_user_token_relationship(db_session, test_user):
    """Test user-token relationship."""
    # Create token for user
    plaintext, key_hash = PersonalAccessToken.generate_key()
    pat = PersonalAccessToken(
        user_id=test_user.id,
        key_hash=key_hash,
        key_prefix=PersonalAccessToken.get_key_prefix(plaintext),
        name="test_key",
    )
    db_session.add(pat)
    await db_session.commit()
    
    # Query user and check relationship
    result = await db_session.execute(
        select(User).where(User.id == test_user.id)
    )
    user = result.scalars().first()
    
    # Note: In SQLite async, relationships might not be auto-loaded
    # So we query explicitly
    result = await db_session.execute(
        select(PersonalAccessToken).where(PersonalAccessToken.user_id == user.id)
    )
    tokens = result.scalars().all()
    
    assert len(tokens) == 1
    assert tokens[0].name == "test_key"
    assert tokens[0].user_id == user.id
