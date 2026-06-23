"""Tests for Watcher proxy dashboard endpoints.

Covers:
  GET  /dashboard/info-items/{id}/watcher-status
  POST /dashboard/info-items/{id}/check-now
  POST /dashboard/info-items/{id}/begin-watching
  POST /dashboard/info-items/{id}/resync-watcher
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from watcher_client import WatchedItemResponse

from src.api.deps import get_watcher_client
from src.api.main import app
from src.core.models import InfoItem, InfoItemSource, InfoSource

_HEADERS = {"X-ExeDev-UserID": "ext-watcher", "X-ExeDev-Email": "watcher@example.com"}
_WI_ID = "01HZZWATCHER00000000000001"
_TS = "2026-06-10T12:00:00+00:00"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _wi(
    health: str = "ok",
    last_checked_at: str | None = _TS,
    *,
    is_active: bool = True,
    archived_at: str | None = None,
) -> WatchedItemResponse:
    return WatchedItemResponse.from_dict(
        {
            "id": _WI_ID,
            "name": "Test Item",
            "description": None,
            "is_active": is_active,
            "archived_at": archived_at,
            "last_reviewed_at": None,
            "last_checked_at": last_checked_at,
            "last_changed_at": None,
            "health_status": health,
            "default_schedule_config": None,
            "content_media_type": None,
            "media_type_essence": None,
            "default_tags": None,
            "effective_url": "https://example.com/",
            "source_specs": [],
            "created_at": _TS,
            "updated_at": _TS,
        }
    )


def _mock_watcher(wi: WatchedItemResponse | None = None) -> MagicMock:
    m = MagicMock()
    m.get_watched_item = AsyncMock(return_value=wi or _wi())
    m.check_now = AsyncMock(return_value=wi or _wi())
    m.patch_watched_item = AsyncMock(return_value=wi or _wi())
    m.provision_watched_item = AsyncMock(return_value=wi or _wi())
    return m


@pytest.fixture(autouse=True)
def _clear_watcher_override():
    """Ensure get_watcher_client override is removed after each test."""
    yield
    app.dependency_overrides.pop(get_watcher_client, None)


# ---------------------------------------------------------------------------
# GET /watcher-status — not configured
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_watcher_status_not_configured(client, session):
    app.dependency_overrides[get_watcher_client] = lambda: None
    item = InfoItem(name="no watcher item")
    session.add(item)
    await session.flush()

    r = await client.get(
        f"/dashboard/info-items/{item.info_item_id}/watcher-status",
        headers=_HEADERS,
    )
    assert r.status_code == 200
    assert "Watcher not configured" in r.text


# ---------------------------------------------------------------------------
# GET /watcher-status — not watching (watcher_item_id IS NULL)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_watcher_status_not_watching(client, session):
    app.dependency_overrides[get_watcher_client] = lambda: _mock_watcher()
    item = InfoItem(name="unwatched item", watcher_item_id=None)
    session.add(item)
    await session.flush()

    r = await client.get(
        f"/dashboard/info-items/{item.info_item_id}/watcher-status",
        headers=_HEADERS,
    )
    assert r.status_code == 200
    assert "Not watching" in r.text
    assert "begin-watching" in r.text


# ---------------------------------------------------------------------------
# GET /watcher-status — ok state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_watcher_status_ok(client, session):
    watcher = _mock_watcher(_wi("ok"))
    app.dependency_overrides[get_watcher_client] = lambda: watcher
    item = InfoItem(name="ok item", watcher_item_id=_WI_ID)
    session.add(item)
    await session.flush()

    r = await client.get(
        f"/dashboard/info-items/{item.info_item_id}/watcher-status",
        headers=_HEADERS,
    )
    assert r.status_code == 200
    assert "OK" in r.text
    assert "check-now" in r.text
    watcher.get_watched_item.assert_awaited_once_with(_WI_ID)


# ---------------------------------------------------------------------------
# GET /watcher-status — paused: Paused badge, Resume, no check-now (#60)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_watcher_status_paused(client, session):
    watcher = _mock_watcher(_wi("ok", is_active=False))
    app.dependency_overrides[get_watcher_client] = lambda: watcher
    item = InfoItem(name="paused item", watcher_item_id=_WI_ID)
    session.add(item)
    await session.flush()

    r = await client.get(
        f"/dashboard/info-items/{item.info_item_id}/watcher-status",
        headers=_HEADERS,
    )
    assert r.status_code == 200
    assert "Paused" in r.text
    assert "Resume" in r.text
    # Check-now suppressed while paused (Watcher 409s on check-now of a paused item).
    assert "check-now" not in r.text


# ---------------------------------------------------------------------------
# GET /watcher-status — archived: Archived badge (not Paused), no toggle (#60)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_watcher_status_archived(client, session):
    watcher = _mock_watcher(_wi("ok", is_active=False, archived_at=_TS))
    app.dependency_overrides[get_watcher_client] = lambda: watcher
    item = InfoItem(name="archived item", watcher_item_id=_WI_ID)
    session.add(item)
    await session.flush()

    r = await client.get(
        f"/dashboard/info-items/{item.info_item_id}/watcher-status",
        headers=_HEADERS,
    )
    assert r.status_code == 200
    assert "Archived" in r.text
    assert "Paused" not in r.text
    assert "toggle-watch-active" not in r.text


# ---------------------------------------------------------------------------
# GET /watcher-status — error state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_watcher_status_error(client, session):
    watcher = _mock_watcher(_wi("error"))
    app.dependency_overrides[get_watcher_client] = lambda: watcher
    item = InfoItem(name="error item", watcher_item_id=_WI_ID)
    session.add(item)
    await session.flush()

    r = await client.get(
        f"/dashboard/info-items/{item.info_item_id}/watcher-status",
        headers=_HEADERS,
    )
    assert r.status_code == 200
    assert "ERROR" in r.text


# ---------------------------------------------------------------------------
# GET /watcher-status — unknown state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_watcher_status_unknown(client, session):
    watcher = _mock_watcher(_wi("unknown", last_checked_at=None))
    app.dependency_overrides[get_watcher_client] = lambda: watcher
    item = InfoItem(name="unknown item", watcher_item_id=_WI_ID)
    session.add(item)
    await session.flush()

    r = await client.get(
        f"/dashboard/info-items/{item.info_item_id}/watcher-status",
        headers=_HEADERS,
    )
    assert r.status_code == 200
    assert "UNKNOWN" in r.text


# ---------------------------------------------------------------------------
# GET /watcher-status — Watcher unreachable (degraded)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_watcher_status_degraded(client, session):
    from watcher_client import WatcherError

    watcher = MagicMock()
    watcher.get_watched_item = AsyncMock(side_effect=WatcherError("timeout"))
    app.dependency_overrides[get_watcher_client] = lambda: watcher
    item = InfoItem(name="degraded item", watcher_item_id=_WI_ID)
    session.add(item)
    await session.flush()

    r = await client.get(
        f"/dashboard/info-items/{item.info_item_id}/watcher-status",
        headers=_HEADERS,
    )
    assert r.status_code == 200
    assert "unavailable" in r.text.lower()


# ---------------------------------------------------------------------------
# POST /check-now — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_now_calls_watcher(client, session):
    watcher = _mock_watcher(_wi("ok"))
    app.dependency_overrides[get_watcher_client] = lambda: watcher
    item = InfoItem(name="check item", watcher_item_id=_WI_ID)
    session.add(item)
    await session.flush()

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/check-now",
        headers=_HEADERS,
    )
    assert r.status_code == 200
    watcher.check_now.assert_awaited_once_with(_WI_ID)
    assert "OK" in r.text


# ---------------------------------------------------------------------------
# POST /check-now — no watcher_item_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_now_not_watching(client, session):
    watcher = _mock_watcher()
    app.dependency_overrides[get_watcher_client] = lambda: watcher
    item = InfoItem(name="no-watch check", watcher_item_id=None)
    session.add(item)
    await session.flush()

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/check-now",
        headers=_HEADERS,
    )
    assert r.status_code == 200
    assert "Not watching" in r.text
    watcher.check_now.assert_not_awaited()


# ---------------------------------------------------------------------------
# POST /check-now — Watcher error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_now_watcher_error(client, session):
    from watcher_client import WatcherError

    watcher = MagicMock()
    watcher.check_now = AsyncMock(side_effect=WatcherError("failed"))
    watcher.get_watched_item = AsyncMock(side_effect=WatcherError("failed"))
    app.dependency_overrides[get_watcher_client] = lambda: watcher
    item = InfoItem(name="error check", watcher_item_id=_WI_ID)
    session.add(item)
    await session.flush()

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/check-now",
        headers=_HEADERS,
    )
    assert r.status_code == 200
    assert "unavailable" in r.text.lower()
    # The action failure is surfaced as a flash, not swallowed silently.
    assert "showFlash" in r.headers.get("HX-Trigger", "")


@pytest.mark.asyncio
async def test_check_now_conflict_flashes_paused_message(client, session):
    # check-now on a paused item → Watcher 409; flash the paused-specific reason,
    # not a generic "unavailable".
    from watcher_client.errors import WatcherConflict

    watcher = MagicMock()
    watcher.check_now = AsyncMock(side_effect=WatcherConflict("paused"))
    watcher.get_watched_item = AsyncMock(return_value=_wi("ok", is_active=False))
    app.dependency_overrides[get_watcher_client] = lambda: watcher
    item = InfoItem(name="paused check", watcher_item_id=_WI_ID)
    session.add(item)
    await session.flush()

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/check-now",
        headers=_HEADERS,
    )
    assert r.status_code == 200
    hx = r.headers.get("HX-Trigger", "")
    assert "showFlash" in hx
    assert "paused" in hx.lower()
    assert "unavailable" not in hx.lower()


@pytest.mark.asyncio
async def test_check_now_failure_flashes_but_keeps_status(client, session):
    # check_now fails but get_watched_item still works → show current status + error flash.
    from watcher_client import WatcherError

    watcher = MagicMock()
    watcher.check_now = AsyncMock(side_effect=WatcherError("boom"))
    watcher.get_watched_item = AsyncMock(return_value=_wi("ok"))
    app.dependency_overrides[get_watcher_client] = lambda: watcher
    item = InfoItem(name="flash check", watcher_item_id=_WI_ID)
    session.add(item)
    await session.flush()

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/check-now",
        headers=_HEADERS,
    )
    assert r.status_code == 200
    hx = r.headers.get("HX-Trigger", "")
    assert "showFlash" in hx
    assert "watcherUpdated" in hx
    assert '"level": "error"' in hx


# ---------------------------------------------------------------------------
# POST /begin-watching — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_begin_watching_provisions_item(client, session):
    watcher = _mock_watcher(_wi("unknown", last_checked_at=None))
    app.dependency_overrides[get_watcher_client] = lambda: watcher

    item = InfoItem(name="new item", watcher_item_id=None)
    src = InfoSource(url="https://example.com/page", source_specs=[])
    session.add(item)
    session.add(src)
    await session.flush()
    session.add(
        InfoItemSource(
            info_item_id=item.info_item_id,
            info_source_id=src.info_source_id,
        )
    )
    await session.flush()

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/begin-watching",
        headers=_HEADERS,
    )
    assert r.status_code == 200
    watcher.provision_watched_item.assert_awaited_once()


# ---------------------------------------------------------------------------
# POST /begin-watching — already provisioned (watcher_item_id already set)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_begin_watching_already_provisioned(client, session):
    watcher = _mock_watcher(_wi("ok"))
    app.dependency_overrides[get_watcher_client] = lambda: watcher
    item = InfoItem(name="already-watched item", watcher_item_id=_WI_ID)
    session.add(item)
    await session.flush()

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/begin-watching",
        headers=_HEADERS,
    )
    assert r.status_code == 200
    assert "OK" in r.text
    watcher.provision_watched_item.assert_not_awaited()


# ---------------------------------------------------------------------------
# POST /begin-watching — no primary source
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_begin_watching_no_primary_source(client, session):
    watcher = _mock_watcher()
    app.dependency_overrides[get_watcher_client] = lambda: watcher
    item = InfoItem(name="sourceless item", watcher_item_id=None)
    session.add(item)
    await session.flush()

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/begin-watching",
        headers=_HEADERS,
    )
    assert r.status_code == 200
    assert "Not watching" in r.text
    watcher.provision_watched_item.assert_not_awaited()


# ---------------------------------------------------------------------------
# POST /begin-watching — WatchedItem already exists in Watcher (state desync)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_begin_watching_adopts_existing_on_conflict(client, session):
    """Reported bug: WatchedItem exists in Watcher but watcher_item_id is NULL.

    Provisioning 409s; begin-watching must adopt the existing WatchedItem and
    render the watching state rather than staying stuck on "Not watching".
    """
    from watcher_client.errors import WatcherConflict

    watcher = _mock_watcher(_wi("ok"))
    watcher.provision_watched_item = AsyncMock(side_effect=WatcherConflict("already exists"))
    watcher.get_by_info_item_id = AsyncMock(return_value=_wi("ok"))
    app.dependency_overrides[get_watcher_client] = lambda: watcher

    item = InfoItem(name="desynced item", watcher_item_id=None)
    src = InfoSource(url="https://example.com/page", source_specs=[])
    session.add(item)
    session.add(src)
    await session.flush()
    session.add(InfoItemSource(info_item_id=item.info_item_id, info_source_id=src.info_source_id))
    await session.flush()

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/begin-watching",
        headers=_HEADERS,
    )
    assert r.status_code == 200
    assert "Not watching" not in r.text
    assert "OK" in r.text  # health badge from the adopted WatchedItem
    watcher.get_by_info_item_id.assert_awaited_once()
    await session.refresh(item)
    assert item.watcher_item_id == _WI_ID


# ---------------------------------------------------------------------------
# POST /resync-watcher — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resync_watcher_calls_patch(client, session):
    watcher = _mock_watcher(_wi("ok"))
    app.dependency_overrides[get_watcher_client] = lambda: watcher

    item = InfoItem(name="resync item", watcher_item_id=_WI_ID)
    src = InfoSource(url="https://example.com/updated", source_specs=[{"schema_version": 1}])
    session.add(item)
    session.add(src)
    await session.flush()
    session.add(
        InfoItemSource(
            info_item_id=item.info_item_id,
            info_source_id=src.info_source_id,
        )
    )
    await session.flush()

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/resync-watcher",
        headers=_HEADERS,
    )
    assert r.status_code == 200
    watcher.patch_watched_item.assert_awaited_once_with(
        _WI_ID,
        effective_url="https://example.com/updated",
        source_specs=[{"schema_version": 1}],
        archiver_info_source_id=str(src.info_source_id),
    )
    assert "OK" in r.text


# ---------------------------------------------------------------------------
# POST /resync-watcher — Watcher raises WatcherError (degraded path)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resync_watcher_error(client, session):
    from watcher_client import WatcherError

    watcher = MagicMock()
    watcher.patch_watched_item = AsyncMock(side_effect=WatcherError("patch failed"))
    watcher.get_watched_item = AsyncMock(side_effect=WatcherError("get failed"))
    app.dependency_overrides[get_watcher_client] = lambda: watcher

    item = InfoItem(name="resync-error item", watcher_item_id=_WI_ID)
    src = InfoSource(url="https://example.com/resync-error", source_specs=[])
    session.add(item)
    session.add(src)
    await session.flush()
    session.add(
        InfoItemSource(
            info_item_id=item.info_item_id,
            info_source_id=src.info_source_id,
        )
    )
    await session.flush()

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/resync-watcher",
        headers=_HEADERS,
    )
    assert r.status_code == 200
    assert "unavailable" in r.text.lower()
    watcher.patch_watched_item.assert_awaited_once()


# ---------------------------------------------------------------------------
# POST /resync-watcher — no watcher_item_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resync_watcher_not_watching(client, session):
    watcher = _mock_watcher()
    app.dependency_overrides[get_watcher_client] = lambda: watcher
    item = InfoItem(name="unwatched resync", watcher_item_id=None)
    session.add(item)
    await session.flush()

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/resync-watcher",
        headers=_HEADERS,
    )
    assert r.status_code == 200
    assert "Not watching" in r.text
    watcher.patch_watched_item.assert_not_awaited()


# ---------------------------------------------------------------------------
# POST /begin-watching — response includes HX-Trigger: watcherUpdated
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_begin_watching_triggers_watcher_updated(client, session):
    watcher = _mock_watcher(_wi("unknown", last_checked_at=None))
    app.dependency_overrides[get_watcher_client] = lambda: watcher

    item = InfoItem(name="begin-watching-trigger", watcher_item_id=None)
    src = InfoSource(url="https://example.com/begin-trigger", source_specs=[])
    session.add(item)
    session.add(src)
    await session.flush()
    session.add(
        InfoItemSource(
            info_item_id=item.info_item_id,
            info_source_id=src.info_source_id,
        )
    )
    await session.flush()

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/begin-watching",
        headers=_HEADERS,
    )
    assert r.status_code == 200
    hx_trigger = r.headers.get("HX-Trigger", "")
    assert "watcherUpdated" in hx_trigger


# ---------------------------------------------------------------------------
# POST /begin-watching — provisioning failure flashes (#61)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_begin_watching_failure_flashes_error(client, session):
    # provision_watched_item fails (swallowed by helper) but the item still has
    # no watcher_item_id → surface an error flash instead of a silent success.
    from watcher_client import WatcherError

    watcher = _mock_watcher(_wi("unknown", last_checked_at=None))
    watcher.provision_watched_item = AsyncMock(side_effect=WatcherError("boom"))
    app.dependency_overrides[get_watcher_client] = lambda: watcher

    item = InfoItem(name="begin-fail", watcher_item_id=None)
    src = InfoSource(url="https://example.com/begin-fail", source_specs=[])
    session.add(item)
    session.add(src)
    await session.flush()
    session.add(InfoItemSource(info_item_id=item.info_item_id, info_source_id=src.info_source_id))
    await session.flush()

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/begin-watching",
        headers=_HEADERS,
    )
    assert r.status_code == 200
    hx = r.headers.get("HX-Trigger", "")
    assert "showFlash" in hx
    assert "watcherUpdated" in hx
    assert '"level": "error"' in hx


@pytest.mark.asyncio
async def test_begin_watching_success_no_flash(client, session):
    watcher = _mock_watcher(_wi("unknown", last_checked_at=None))
    app.dependency_overrides[get_watcher_client] = lambda: watcher

    item = InfoItem(name="begin-ok", watcher_item_id=None)
    src = InfoSource(url="https://example.com/begin-ok", source_specs=[])
    session.add(item)
    session.add(src)
    await session.flush()
    session.add(InfoItemSource(info_item_id=item.info_item_id, info_source_id=src.info_source_id))
    await session.flush()

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/begin-watching",
        headers=_HEADERS,
    )
    assert r.status_code == 200
    hx = r.headers.get("HX-Trigger", "")
    assert "watcherUpdated" in hx
    assert "showFlash" not in hx


@pytest.mark.asyncio
async def test_begin_watching_no_primary_source_flashes_error(client, session):
    # No active binding → nothing to watch. Previously a silent re-render (#61 gap).
    watcher = _mock_watcher()
    app.dependency_overrides[get_watcher_client] = lambda: watcher
    item = InfoItem(name="begin-no-source", watcher_item_id=None)
    session.add(item)
    await session.flush()

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/begin-watching",
        headers=_HEADERS,
    )
    assert r.status_code == 200
    hx = r.headers.get("HX-Trigger", "")
    assert "showFlash" in hx
    assert '"level": "error"' in hx
    watcher.provision_watched_item.assert_not_awaited()


# ---------------------------------------------------------------------------
# POST /resync-watcher — sync failure flashes (#61)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resync_watcher_failure_flashes_error(client, session):
    # patch fails (swallowed by helper) but get_watched_item still works → the
    # status partial would look healthy; surface the action failure as a flash.
    from watcher_client import WatcherError

    watcher = _mock_watcher(_wi("ok"))
    watcher.patch_watched_item = AsyncMock(side_effect=WatcherError("boom"))
    app.dependency_overrides[get_watcher_client] = lambda: watcher

    item = InfoItem(name="resync-fail", watcher_item_id=_WI_ID)
    src = InfoSource(url="https://example.com/resync-fail", source_specs=[])
    session.add(item)
    session.add(src)
    await session.flush()
    session.add(InfoItemSource(info_item_id=item.info_item_id, info_source_id=src.info_source_id))
    await session.flush()

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/resync-watcher",
        headers=_HEADERS,
    )
    assert r.status_code == 200
    hx = r.headers.get("HX-Trigger", "")
    assert "showFlash" in hx
    assert "watcherUpdated" in hx
    assert '"level": "error"' in hx


@pytest.mark.asyncio
async def test_resync_watcher_success_no_flash(client, session):
    watcher = _mock_watcher(_wi("ok"))
    app.dependency_overrides[get_watcher_client] = lambda: watcher

    item = InfoItem(name="resync-ok", watcher_item_id=_WI_ID)
    src = InfoSource(url="https://example.com/resync-ok", source_specs=[])
    session.add(item)
    session.add(src)
    await session.flush()
    session.add(InfoItemSource(info_item_id=item.info_item_id, info_source_id=src.info_source_id))
    await session.flush()

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/resync-watcher",
        headers=_HEADERS,
    )
    assert r.status_code == 200
    hx = r.headers.get("HX-Trigger", "")
    assert "watcherUpdated" in hx
    assert "showFlash" not in hx


@pytest.mark.asyncio
async def test_resync_watcher_no_primary_source_flashes_error(client, session):
    # Watched item whose active binding is gone → nothing to re-sync (#61 gap).
    watcher = _mock_watcher(_wi("ok"))
    app.dependency_overrides[get_watcher_client] = lambda: watcher
    item = InfoItem(name="resync-no-source", watcher_item_id=_WI_ID)
    session.add(item)
    await session.flush()

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/resync-watcher",
        headers=_HEADERS,
    )
    assert r.status_code == 200
    hx = r.headers.get("HX-Trigger", "")
    assert "showFlash" in hx
    assert '"level": "error"' in hx
    watcher.patch_watched_item.assert_not_awaited()


@pytest.mark.asyncio
async def test_begin_watching_no_source_unconfigured_watcher_no_flash(client, session):
    # No primary source AND no Watcher configured → the partial shows
    # not_configured; suppress the missing-source flash so it doesn't mislead (#61).
    app.dependency_overrides[get_watcher_client] = lambda: None
    item = InfoItem(name="begin-no-source-no-watcher", watcher_item_id=None)
    session.add(item)
    await session.flush()

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/begin-watching",
        headers=_HEADERS,
    )
    assert r.status_code == 200
    hx = r.headers.get("HX-Trigger", "")
    assert "showFlash" not in hx


# ---------------------------------------------------------------------------
# POST /toggle-watch-active — pause / resume (#60)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_toggle_pause_calls_patch(client, session):
    # Active item, request active=false → patch is_active=False, fires watcherUpdated.
    watcher = _mock_watcher(_wi("ok", is_active=False))
    app.dependency_overrides[get_watcher_client] = lambda: watcher
    item = InfoItem(name="pause item", watcher_item_id=_WI_ID)
    session.add(item)
    await session.flush()

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/toggle-watch-active",
        headers=_HEADERS,
        data={"active": "false"},
    )
    assert r.status_code == 200
    watcher.patch_watched_item.assert_awaited_once_with(_WI_ID, is_active=False)
    assert "watcherUpdated" in r.headers.get("HX-Trigger", "")
    # Re-rendered strip reflects the paused state and offers Resume.
    assert "Paused" in r.text
    assert "Resume" in r.text
    # Check-now suppressed in the strip once paused.
    assert "check-now" not in r.text


@pytest.mark.asyncio
async def test_toggle_resume_calls_patch(client, session):
    watcher = _mock_watcher(_wi("ok", is_active=True))
    app.dependency_overrides[get_watcher_client] = lambda: watcher
    item = InfoItem(name="resume item", watcher_item_id=_WI_ID)
    session.add(item)
    await session.flush()

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/toggle-watch-active",
        headers=_HEADERS,
        data={"active": "true"},
    )
    assert r.status_code == 200
    watcher.patch_watched_item.assert_awaited_once_with(_WI_ID, is_active=True)


@pytest.mark.asyncio
async def test_toggle_not_watching_is_noop(client, session):
    watcher = _mock_watcher()
    app.dependency_overrides[get_watcher_client] = lambda: watcher
    item = InfoItem(name="no-watch toggle", watcher_item_id=None)
    session.add(item)
    await session.flush()

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/toggle-watch-active",
        headers=_HEADERS,
        data={"active": "false"},
    )
    assert r.status_code == 200
    assert "Not watching" in r.text
    watcher.patch_watched_item.assert_not_awaited()


@pytest.mark.asyncio
async def test_toggle_conflict_does_not_crash(client, session):
    # Watcher 409 (e.g. archived item) → re-render, no 500.
    from watcher_client.errors import WatcherConflict

    watcher = MagicMock()
    watcher.patch_watched_item = AsyncMock(side_effect=WatcherConflict("archived"))
    watcher.get_watched_item = AsyncMock(return_value=_wi("ok"))
    app.dependency_overrides[get_watcher_client] = lambda: watcher
    item = InfoItem(name="conflict toggle", watcher_item_id=_WI_ID)
    session.add(item)
    await session.flush()

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/toggle-watch-active",
        headers=_HEADERS,
        data={"active": "false"},
    )
    assert r.status_code == 200
    # The conflict is surfaced to the operator, not swallowed.
    assert "showFlash" in r.headers.get("HX-Trigger", "")


@pytest.mark.asyncio
async def test_toggle_failure_flashes_error(client, session):
    from watcher_client import WatcherError

    watcher = MagicMock()
    watcher.patch_watched_item = AsyncMock(side_effect=WatcherError("down"))
    watcher.get_watched_item = AsyncMock(return_value=_wi("ok"))
    app.dependency_overrides[get_watcher_client] = lambda: watcher
    item = InfoItem(name="toggle flash", watcher_item_id=_WI_ID)
    session.add(item)
    await session.flush()

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/toggle-watch-active",
        headers=_HEADERS,
        data={"active": "false"},
    )
    assert r.status_code == 200
    hx = r.headers.get("HX-Trigger", "")
    assert "showFlash" in hx
    assert '"level": "error"' in hx
