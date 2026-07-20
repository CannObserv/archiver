"""List-route offset overflow tests — offsets beyond int64 return 422, not 500 (#88)."""

import pytest

HEADERS = {"X-API-Key": "test-secret-key"}

INT64_MAX = 2**63 - 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/domains",
        "/api/v1/info-items",
        "/api/v1/info-sources",
        "/api/v1/rep-specs",
    ],
)
async def test_list_offset_beyond_int64_returns_422(client, path):
    resp = await client.get(f"{path}?offset={2**63}", headers=HEADERS)
    assert resp.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/domains",
        "/api/v1/info-items",
        "/api/v1/info-sources",
        "/api/v1/rep-specs",
    ],
)
async def test_list_offset_at_int64_max_is_accepted(client, path):
    resp = await client.get(f"{path}?offset={INT64_MAX}", headers=HEADERS)
    assert resp.status_code == 200
