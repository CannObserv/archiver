"""Health endpoint smoke tests."""

import pytest

from src.core import build


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


@pytest.mark.asyncio
async def test_health_reports_the_release_revision(client, monkeypatch, tmp_path):
    """archiver#330 D8: in a release, ``REVISION`` wins over the unit's stamp."""
    (tmp_path / "REVISION").write_text("0123456789ab\n")
    monkeypatch.setattr(build, "ROOT", tmp_path)
    monkeypatch.setenv("BUILD_ID", "abc1234-dirty")
    response = await client.get("/health")
    assert response.json() == {"status": "ok", "build_id": "0123456789ab"}
