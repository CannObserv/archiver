"""ORM model tests for AppUser and ApiKey."""

import pytest
from sqlalchemy.exc import IntegrityError

from src.core.models import ApiKey, AppUser


@pytest.mark.asyncio
async def test_create_app_user(session):
    user = AppUser(external_id="ext-001", email="alice@example.com")
    session.add(user)
    await session.flush()

    result = await session.get(AppUser, user.id)
    assert result is not None
    assert result.email == "alice@example.com"
    assert result.external_id == "ext-001"
    assert result.id is not None
    assert result.created_at is not None
    assert result.updated_at is not None


@pytest.mark.asyncio
async def test_app_user_external_id_unique(session):
    user1 = AppUser(external_id="ext-dup", email="u1@example.com")
    user2 = AppUser(external_id="ext-dup", email="u2@example.com")
    session.add_all([user1, user2])
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_app_user_email_not_unique(session):
    # Identity is external_id; email is descriptive data the proxy reports and
    # does not guarantee unique (#177). Two identities may share a mailbox.
    user1 = AppUser(external_id="ext-a", email="dup@example.com")
    user2 = AppUser(external_id="ext-b", email="dup@example.com")
    session.add_all([user1, user2])
    await session.flush()

    assert user1.id != user2.id
    assert user1.email == user2.email


@pytest.mark.asyncio
async def test_create_api_key(session):
    user = AppUser(external_id="ext-002", email="bob@example.com")
    session.add(user)
    await session.flush()

    key = ApiKey(
        user_id=user.id,
        label="My Key",
        key_prefix="co_12345",
        key_hash="sha256hashvalue",
    )
    session.add(key)
    await session.flush()

    result = await session.get(ApiKey, key.id)
    assert result is not None
    assert result.label == "My Key"
    assert result.user_id == user.id
    assert result.key_prefix == "co_12345"
    assert result.key_hash == "sha256hashvalue"
    assert result.last_used_at is None
    assert result.created_at is not None
