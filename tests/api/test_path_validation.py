"""Path-param ULID validation tests — malformed ULIDs return 422, not 404."""

import pytest

HEADERS = {"X-API-Key": "test-secret-key"}


@pytest.fixture(autouse=True)
def _set_api_key(monkeypatch):
    monkeypatch.setenv("ARCHIVER_API_KEY", "test-secret-key")


@pytest.mark.asyncio
async def test_get_info_item_with_malformed_ulid_returns_422(client):
    r = await client.get("/api/v1/info-items/not-a-ulid", headers=HEADERS)
    assert r.status_code == 422
