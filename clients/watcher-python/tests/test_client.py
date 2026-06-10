"""respx-mocked tests for WatcherClient adapter layer."""

import pytest
import respx
from httpx import Response

from watcher_client import WatcherClient, WatchedItemResponse, WatchHealthStatus
from watcher_client.errors import (
    WatcherAuthError,
    WatcherConflict,
    WatcherNotFound,
    WatcherValidationError,
)

BASE_URL = "http://watcher.test"
_TS = "2026-06-10T00:00:00Z"
_WI_ID = "01HZZWATCHER00000000000001"
_INFO_ITEM_ID = "01HZZARCHIVER00000000000001"
_INFO_SRC_ID = "01HZZARCHIVER00000000000002"


def _wi_payload(wi_id: str = _WI_ID, **overrides) -> dict:
    base = {
        "id": wi_id,
        "name": "Test WatchedItem",
        "description": None,
        "is_active": True,
        "archived_at": None,
        "last_reviewed_at": None,
        "last_checked_at": None,
        "last_changed_at": None,
        "health_status": "unknown",
        "default_schedule_config": None,
        "default_content_type": None,
        "default_tags": None,
        "effective_url": "https://example.com/data",
        "source_specs": [],
        "archiver_info_item_id": _INFO_ITEM_ID,
        "archiver_info_source_id": _INFO_SRC_ID,
        "domain_name": "example.com",
        "domain_suspended": False,
        "created_at": _TS,
        "updated_at": _TS,
    }
    base.update(overrides)
    return base


@pytest.fixture
def client():
    return WatcherClient(base_url=BASE_URL, api_key="test-key")


@respx.mock
@pytest.mark.asyncio
async def test_provision_watched_item(client):
    payload = _wi_payload()
    respx.post(f"{BASE_URL}/api/v1/watched-items").mock(return_value=Response(201, json=payload))

    result = await client.provision_watched_item(
        url="https://example.com/data",
        source_specs=[{"schema_version": 1, "extraction": {"type": "full_page"}}],
        info_item_id=_INFO_ITEM_ID,
        archiver_info_source_id=_INFO_SRC_ID,
    )

    assert isinstance(result, WatchedItemResponse)
    assert result.id == _WI_ID
    assert result.health_status == WatchHealthStatus.UNKNOWN
    assert result.effective_url == "https://example.com/data"


@respx.mock
@pytest.mark.asyncio
async def test_provision_sets_auth_header(client):
    payload = _wi_payload()
    route = respx.post(f"{BASE_URL}/api/v1/watched-items").mock(
        return_value=Response(201, json=payload)
    )

    await client.provision_watched_item(
        url="https://example.com/data",
        source_specs=[],
        info_item_id=_INFO_ITEM_ID,
        archiver_info_source_id=_INFO_SRC_ID,
    )

    assert route.called
    assert route.calls.last.request.headers.get("x-api-key") == "test-key"


@respx.mock
@pytest.mark.asyncio
async def test_patch_watched_item_effective_url(client):
    updated = _wi_payload(effective_url="https://example.com/new-data")
    route = respx.patch(f"{BASE_URL}/api/v1/watched-items/{_WI_ID}").mock(
        return_value=Response(200, json=updated)
    )

    result = await client.patch_watched_item(
        _WI_ID,
        effective_url="https://example.com/new-data",
        source_specs=[{"schema_version": 1, "extraction": {"type": "full_page"}}],
        archiver_info_source_id=_INFO_SRC_ID,
    )

    assert result.effective_url == "https://example.com/new-data"
    import json

    sent_body = json.loads(route.calls.last.request.content)
    assert "effective_url" in sent_body
    assert "source_specs" in sent_body
    assert "archiver_info_source_id" in sent_body


@respx.mock
@pytest.mark.asyncio
async def test_patch_watched_item_omits_none_fields(client):
    route = respx.patch(f"{BASE_URL}/api/v1/watched-items/{_WI_ID}").mock(
        return_value=Response(200, json=_wi_payload())
    )

    await client.patch_watched_item(_WI_ID, archiver_info_source_id=_INFO_SRC_ID)

    import json

    sent_body = json.loads(route.calls.last.request.content)
    assert "effective_url" not in sent_body
    assert "source_specs" not in sent_body
    assert sent_body["archiver_info_source_id"] == _INFO_SRC_ID


@respx.mock
@pytest.mark.asyncio
async def test_get_watched_item(client):
    respx.get(f"{BASE_URL}/api/v1/watched-items/{_WI_ID}").mock(
        return_value=Response(200, json=_wi_payload())
    )
    result = await client.get_watched_item(_WI_ID)
    assert result.id == _WI_ID


@respx.mock
@pytest.mark.asyncio
async def test_get_watched_item_not_found(client):
    respx.get(f"{BASE_URL}/api/v1/watched-items/{_WI_ID}").mock(
        return_value=Response(404, json={"detail": "WatchedItem not found"})
    )
    with pytest.raises(WatcherNotFound):
        await client.get_watched_item(_WI_ID)


@respx.mock
@pytest.mark.asyncio
async def test_get_by_info_item_id_found(client):
    respx.get(f"{BASE_URL}/api/v1/watched-items").mock(
        return_value=Response(200, json=[_wi_payload()])
    )
    result = await client.get_by_info_item_id(_INFO_ITEM_ID)
    assert result is not None
    assert result.id == _WI_ID


@respx.mock
@pytest.mark.asyncio
async def test_get_by_info_item_id_not_found(client):
    respx.get(f"{BASE_URL}/api/v1/watched-items").mock(return_value=Response(200, json=[]))
    result = await client.get_by_info_item_id(_INFO_ITEM_ID)
    assert result is None


@respx.mock
@pytest.mark.asyncio
async def test_check_now(client):
    respx.post(f"{BASE_URL}/api/v1/watched-items/{_WI_ID}/check-now").mock(
        return_value=Response(202, json=_wi_payload())
    )
    result = await client.check_now(_WI_ID)
    assert result.id == _WI_ID


@respx.mock
@pytest.mark.asyncio
async def test_check_now_archived_raises_conflict(client):
    respx.post(f"{BASE_URL}/api/v1/watched-items/{_WI_ID}/check-now").mock(
        return_value=Response(409, json={"detail": "WatchedItem is archived"})
    )
    with pytest.raises(WatcherConflict):
        await client.check_now(_WI_ID)


@respx.mock
@pytest.mark.asyncio
async def test_check_now_no_url_raises_validation(client):
    respx.post(f"{BASE_URL}/api/v1/watched-items/{_WI_ID}/check-now").mock(
        return_value=Response(422, json={"detail": "WatchedItem has no effective url"})
    )
    with pytest.raises(WatcherValidationError):
        await client.check_now(_WI_ID)


@respx.mock
@pytest.mark.asyncio
async def test_list_revisions(client):
    revision = {
        "id": "01HZZREV000000000000000001",
        "watched_item_id": _WI_ID,
        "content_fingerprint": "sha256:abc123",
        "captured_at": _TS,
        "content_size_bytes": 1024,
        "archiver_revision_id": None,
        "schema_version": 1,
    }
    respx.get(f"{BASE_URL}/api/v1/watched-items/{_WI_ID}/revisions").mock(
        return_value=Response(200, json=[revision])
    )
    results = await client.list_revisions(_WI_ID)
    assert len(results) == 1
    assert results[0].content_fingerprint == "sha256:abc123"


@respx.mock
@pytest.mark.asyncio
async def test_auth_error_raises_watcher_auth_error(client):
    respx.get(f"{BASE_URL}/api/v1/watched-items/{_WI_ID}").mock(
        return_value=Response(403, json={"detail": "Forbidden"})
    )
    with pytest.raises(WatcherAuthError):
        await client.get_watched_item(_WI_ID)
