"""Tests for DB-backed require_api_key dep (Epic 2 migration)."""

import pytest

from src.core.models import ApiKey, AppUser
from src.dashboard.deps import generate_api_key

# A key not in the DB — used for "wrong key" assertions.
_BAD_KEY = "wrong-key-value"

# An existing v1 route that is cheap and available in tests.
_V1_URL = "/api/v1/info-items"


@pytest.mark.asyncio
async def test_missing_key_returns_403(client):
    response = await client.get(_V1_URL)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_wrong_key_returns_401(client):
    response = await client.get(_V1_URL, headers={"X-API-Key": _BAD_KEY})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_valid_db_key_allows_request(client, session):
    user = AppUser(external_id="ext-auth-test", email="auth@example.com")
    session.add(user)
    await session.flush()
    raw_key, key_prefix, key_hash = generate_api_key()
    api_key = ApiKey(user_id=user.id, label="Auth test", key_prefix=key_prefix, key_hash=key_hash)
    session.add(api_key)
    await session.flush()

    response = await client.get(_V1_URL, headers={"X-API-Key": raw_key})
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_valid_key_updates_last_used_at(client, session):
    user = AppUser(external_id="ext-lastused", email="lastused@example.com")
    session.add(user)
    await session.flush()
    raw_key, key_prefix, key_hash = generate_api_key()
    api_key = ApiKey(
        user_id=user.id, label="Last-used test", key_prefix=key_prefix, key_hash=key_hash
    )
    session.add(api_key)
    await session.flush()

    assert api_key.last_used_at is None

    await client.get(_V1_URL, headers={"X-API-Key": raw_key})

    # Expire identity-map cache so re-query fetches from the flushed state.
    await session.refresh(api_key)
    assert api_key.last_used_at is not None
