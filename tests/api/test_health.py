"""Health endpoint smoke tests."""

import pytest


@pytest.mark.asyncio
async def test_health_returns_ok(client, monkeypatch):
    monkeypatch.delenv("BUILD_ID", raising=False)
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "build_id": None}


@pytest.mark.asyncio
async def test_health_reports_build_id_when_env_set(client, monkeypatch):
    monkeypatch.setenv("BUILD_ID", "abc1234-dirty")
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "build_id": "abc1234-dirty"}
