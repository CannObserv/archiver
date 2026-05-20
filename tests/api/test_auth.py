"""X-API-Key bearer auth tests for the Archiver service."""

import pytest


@pytest.mark.asyncio
async def test_missing_key_returns_403(client):
    response = await client.get("/api/v1/info-items")
    assert response.status_code == 403
    body = response.json()
    assert body["detail"]["kind"] == "auth"
    assert body["detail"]["message"] == "Not authenticated"
    assert body["detail"]["errors"] == []


@pytest.mark.asyncio
async def test_invalid_key_returns_401(client):
    response = await client.get("/api/v1/info-items", headers={"X-API-Key": "wrong"})
    assert response.status_code == 401
    body = response.json()
    assert body["detail"]["kind"] == "auth"
    assert body["detail"]["message"] == "Invalid API key"
    assert body["detail"]["errors"] == []


@pytest.mark.asyncio
async def test_valid_key_passes(client):
    response = await client.get("/api/v1/info-items", headers={"X-API-Key": "test-secret-key"})
    assert response.status_code == 200  # empty list
