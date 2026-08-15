"""Tests for Watcher proxy dashboard endpoints.

Covers:
  GET  /dashboard/info-items/{id}/watcher-status
  POST /dashboard/info-items/{id}/check-now
  POST /dashboard/info-items/{id}/begin-watching
  POST /dashboard/info-items/{id}/resync-watcher
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from watcher_client import WatchedItemResponse, WatcherError
from watcher_client.errors import WatcherConflict, WatcherResponseError

import src.dashboard.routes.info_items as dash_items
from src.api.deps import get_watcher_client
from src.api.main import app
from src.core.models import InfoItem, InfoItemSource, InfoSource, WatchStatus

_HEADERS = {"X-ExeDev-UserID": "ext-watcher", "X-ExeDev-Email": "watcher@example.com"}
_WI_ID = "01HZZWATCHER00000000000001"
_TS = "2026-06-10T12:00:00+00:00"
_STATUS_TS = datetime(2026, 6, 10, 11, 0, tzinfo=UTC)


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


def _seed_status(session, item: InfoItem, **overrides) -> None:
    """Seed the local watch_status cache the panel renders from (archiver#151)."""
    defaults = dict(
        info_item_id=item.info_item_id,
        applied_generation=item.announcement_generation,
        applied_active=True,
        applied_interval=None,
        last_attempt_at=_STATUS_TS,
        last_observed_at=_STATUS_TS,
        health="ok",
        occurred_at=_STATUS_TS,
    )
    defaults.update(overrides)
    session.add(WatchStatus(**defaults))


@pytest.fixture(autouse=True)
def _clear_watcher_override():
    """Ensure get_watcher_client override is removed after each test."""
    yield
    app.dependency_overrides.pop(get_watcher_client, None)


# ---------------------------------------------------------------------------
# GET /watcher-status — Watcher client not configured: local render, no actions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_watcher_status_not_configured(client, session):
    """The render is local state (archiver#151), so an unconfigured Watcher no
    longer blanks the panel — it only hides the action buttons."""
    app.dependency_overrides[get_watcher_client] = lambda: None
    item = InfoItem(name="no watcher item")
    session.add(item)
    await session.flush()

    r = await client.get(
        f"/dashboard/info-items/{item.info_item_id}/watcher-status",
        headers=_HEADERS,
    )
    assert r.status_code == 200
    assert "Not watching" in r.text
    assert "begin-watching" not in r.text  # no client to provision with


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
    _seed_status(session, item)
    await session.flush()

    r = await client.get(
        f"/dashboard/info-items/{item.info_item_id}/watcher-status",
        headers=_HEADERS,
    )
    assert r.status_code == 200
    assert "OK" in r.text
    assert "check-now" in r.text
    # The whole point of archiver#151: the render makes zero SDK calls.
    watcher.get_watched_item.assert_not_awaited()


# ---------------------------------------------------------------------------
# GET /watcher-status — paused: Paused badge, Resume, no check-now (#60)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_watcher_status_paused(client, session):
    """applied_active=False is a legitimate reported state, not absence."""
    watcher = _mock_watcher()
    app.dependency_overrides[get_watcher_client] = lambda: watcher
    item = InfoItem(name="paused item", watcher_item_id=_WI_ID)
    session.add(item)
    await session.flush()
    _seed_status(session, item, applied_active=False)
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
# GET /watcher-status — no status yet: the fourth state (archiver#151)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_watcher_status_no_status_yet_is_distinct(client, session):
    """Provisioned but Watcher has never reported — distinct from paused and
    from healthy. A booting consumer with an empty replay lands here."""
    watcher = _mock_watcher()
    app.dependency_overrides[get_watcher_client] = lambda: watcher
    item = InfoItem(name="silent item", watcher_item_id=_WI_ID)
    session.add(item)
    await session.flush()

    r = await client.get(
        f"/dashboard/info-items/{item.info_item_id}/watcher-status",
        headers=_HEADERS,
    )
    assert r.status_code == 200
    assert "NO STATUS YET" in r.text
    assert "Paused" not in r.text
    assert "OK" not in r.text
    assert "Not watching" not in r.text
    watcher.get_watched_item.assert_not_awaited()


# ---------------------------------------------------------------------------
# GET /watcher-status — error state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_watcher_status_error(client, session):
    app.dependency_overrides[get_watcher_client] = lambda: _mock_watcher()
    item = InfoItem(name="error item", watcher_item_id=_WI_ID)
    session.add(item)
    await session.flush()
    _seed_status(session, item, health="error")
    await session.flush()

    r = await client.get(
        f"/dashboard/info-items/{item.info_item_id}/watcher-status",
        headers=_HEADERS,
    )
    assert r.status_code == 200
    assert "ERROR" in r.text


# ---------------------------------------------------------------------------
# GET /watcher-status — unknown health value renders verbatim, never as healthy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_watcher_status_unknown_health_renders_verbatim_not_ok(client, session):
    """`health` is an open vocabulary — "ok" is the only healthy value. A token
    the panel has never seen renders verbatim as non-healthy (badge--danger)."""
    app.dependency_overrides[get_watcher_client] = lambda: _mock_watcher()
    item = InfoItem(name="unknown item", watcher_item_id=_WI_ID)
    session.add(item)
    await session.flush()
    _seed_status(session, item, health="degraded-someday")
    await session.flush()

    r = await client.get(
        f"/dashboard/info-items/{item.info_item_id}/watcher-status",
        headers=_HEADERS,
    )
    assert r.status_code == 200
    assert "DEGRADED-SOMEDAY" in r.text
    assert "badge--danger" in r.text
    assert "badge--success" not in r.text


# ---------------------------------------------------------------------------
# GET /watcher-status — a broken Watcher cannot break the render (archiver#151)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_watcher_status_renders_despite_watcher_being_down(client, session):
    """The SDK-era render degraded when Watcher was unreachable; the local
    render cannot — the SDK is never called on the read path."""
    watcher = MagicMock()
    watcher.get_watched_item = AsyncMock(side_effect=WatcherError("timeout"))
    app.dependency_overrides[get_watcher_client] = lambda: watcher
    item = InfoItem(name="degraded item", watcher_item_id=_WI_ID)
    session.add(item)
    await session.flush()
    _seed_status(session, item)
    await session.flush()

    r = await client.get(
        f"/dashboard/info-items/{item.info_item_id}/watcher-status",
        headers=_HEADERS,
    )
    assert r.status_code == 200
    assert "OK" in r.text
    assert "unavailable" not in r.text.lower()
    watcher.get_watched_item.assert_not_awaited()


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
    _seed_status(session, item)
    await session.flush()

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/check-now",
        headers=_HEADERS,
    )
    assert r.status_code == 200
    watcher.check_now.assert_awaited_once_with(_WI_ID)
    assert "OK" in r.text  # re-render comes from the local cache


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
    # The action failure is surfaced as a flash; the body renders local state
    # (archiver#151) and no longer degrades on a Watcher outage.
    hx = r.headers.get("HX-Trigger", "")
    assert "showFlash" in hx
    assert "unavailable" in hx.lower()


@pytest.mark.asyncio
async def test_check_now_contract_error_flashes_stale_not_unavailable(client, session):
    """A WatcherResponseError (stale SDK / response drift) must flash an honest
    'out of date' message, not 'unavailable. Try again shortly' — retrying a
    contract mismatch never helps."""
    watcher = MagicMock()
    watcher.check_now = AsyncMock(side_effect=WatcherResponseError("stale SDK"))
    watcher.get_watched_item = AsyncMock(side_effect=WatcherResponseError("stale SDK"))
    app.dependency_overrides[get_watcher_client] = lambda: watcher
    item = InfoItem(name="contract check", watcher_item_id=_WI_ID)
    session.add(item)
    await session.flush()

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/check-now",
        headers=_HEADERS,
    )
    assert r.status_code == 200
    hx = r.headers.get("HX-Trigger", "")
    assert "showFlash" in hx
    assert "out of date" in hx.lower()
    assert "unavailable" not in hx.lower()
    assert "try again" not in hx.lower()


@pytest.mark.asyncio
async def test_check_now_conflict_flashes_paused_message(client, session):
    # check-now on a paused item → Watcher 409; flash the paused-specific reason,
    # not a generic "unavailable".
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


@pytest.mark.asyncio
async def test_begin_watching_contract_error_flashes_stale_not_unavailable(client, session):
    """provision_on_create returns CONTRACT_ERROR (response drift) → begin-watching
    flashes an honest 'out of date' message, not the transport 'unavailable' copy."""
    watcher = _mock_watcher()
    watcher.provision_watched_item = AsyncMock(side_effect=WatcherResponseError("stale SDK"))
    app.dependency_overrides[get_watcher_client] = lambda: watcher

    item = InfoItem(name="contract item", watcher_item_id=None)
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
    hx = r.headers.get("HX-Trigger", "")
    assert "showFlash" in hx
    assert "out of date" in hx.lower()
    assert "unavailable" not in hx.lower()
    assert "try again" not in hx.lower()


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
    # Already provisioned, Watcher hasn't reported → the fourth state renders.
    assert "NO STATUS YET" in r.text
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
    # Adopted, but Watcher hasn't reported on the status stream yet.
    assert "NO STATUS YET" in r.text
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


# ---------------------------------------------------------------------------
# POST /resync-watcher — Watcher raises WatcherError (degraded path)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resync_watcher_error(client, session):
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
    # The failure is surfaced as a flash; the body renders local state.
    hx = r.headers.get("HX-Trigger", "")
    assert "showFlash" in hx
    assert "unavailable" in hx.lower()
    watcher.patch_watched_item.assert_awaited_once()


@pytest.mark.asyncio
async def test_resync_watcher_contract_error_flashes_stale_not_unavailable(client, session):
    """sync_on_source_swap returns CONTRACT_ERROR (response drift) → resync flashes
    an honest 'out of date' message, not the transport 'unavailable' copy."""
    watcher = MagicMock()
    watcher.patch_watched_item = AsyncMock(side_effect=WatcherResponseError("stale SDK"))
    watcher.get_watched_item = AsyncMock(return_value=_wi("ok"))
    app.dependency_overrides[get_watcher_client] = lambda: watcher

    item = InfoItem(name="resync-contract item", watcher_item_id=_WI_ID)
    src = InfoSource(url="https://example.com/resync-contract", source_specs=[])
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
    watcher.patch_watched_item.assert_awaited_once()
    hx = r.headers.get("HX-Trigger", "")
    assert "showFlash" in hx
    assert "out of date" in hx.lower()
    assert "unavailable" not in hx.lower()
    assert "try again" not in hx.lower()


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
async def test_toggle_pause_writes_locally_and_never_calls_watcher(client, session):
    """archiver#158: pause is an ``UPDATE`` plus an announcement, not a PATCH.

    The re-render is still local *applied* state (archiver#151), so the strip
    reflects the pause only once Watcher reports it back on
    ``info.watch-status`` — the lag is the announcement round-trip and shows as
    generation drift rather than disappearing.
    """
    watcher = _mock_watcher(_wi("ok", is_active=False))
    app.dependency_overrides[get_watcher_client] = lambda: watcher
    item = InfoItem(name="pause item", watcher_item_id=_WI_ID)
    session.add(item)
    await session.flush()
    _seed_status(session, item, applied_active=False)  # Watcher has reported the pause
    await session.flush()

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/toggle-watch-active",
        headers=_HEADERS,
        data={"active": "false"},
    )
    assert r.status_code == 200
    watcher.patch_watched_item.assert_not_awaited()
    await session.refresh(item)
    assert item.watch_active is False
    assert "watcherUpdated" in r.headers.get("HX-Trigger", "")
    # Re-rendered strip reflects the applied paused state and offers Resume.
    assert "Paused" in r.text
    assert "Resume" in r.text
    # Check-now suppressed in the strip once paused.
    assert "check-now" not in r.text


@pytest.mark.asyncio
async def test_toggle_resume_writes_locally(client, session):
    watcher = _mock_watcher(_wi("ok", is_active=True))
    app.dependency_overrides[get_watcher_client] = lambda: watcher
    item = InfoItem(name="resume item", watcher_item_id=_WI_ID, watch_active=False)
    session.add(item)
    await session.flush()

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/toggle-watch-active",
        headers=_HEADERS,
        data={"active": "true"},
    )
    assert r.status_code == 200
    watcher.patch_watched_item.assert_not_awaited()
    await session.refresh(item)
    assert item.watch_active is True


@pytest.mark.asyncio
async def test_toggle_is_not_offered_without_an_announceable_source(client, session):
    """The affordance is gated on announceability, not on the Watcher link
    (CR round 1, finding 3).

    An item whose primary binding was deactivated keeps its `watcher_item_id`
    and still renders `watching`, but pausing it would announce a **tombstone**
    and burn a generation — which then reads as drift on the same panel, for an
    item where nothing is actually wrong. `can_act` cannot express that: it
    tests the link, and the link outlives the binding.
    """
    app.dependency_overrides[get_watcher_client] = lambda: _mock_watcher(_wi("ok"))
    item = InfoItem(name="unbound toggle", watcher_item_id=_WI_ID)
    session.add(item)
    await session.flush()
    _seed_status(session, item)
    await session.flush()

    r = await client.get(
        f"/dashboard/info-items/{item.info_item_id}/watcher-section",
        headers=_HEADERS,
    )
    assert r.status_code == 200
    assert "toggle-watch-active" not in r.text
    # The other actions stay: re-sync is how an operator recovers from this.
    assert "resync-watcher" in r.text


@pytest.mark.asyncio
async def test_toggle_is_offered_once_a_source_carries_specs(client, session):
    """The mirror of the case above — the gate is announceability, so a bound
    source with non-empty specs restores the affordance."""
    app.dependency_overrides[get_watcher_client] = lambda: _mock_watcher(_wi("ok"))
    item = InfoItem(name="bound toggle", watcher_item_id=_WI_ID)
    src = InfoSource(
        url="https://example.com/bound-toggle",
        source_specs=[{"schema_version": 1, "extraction": {"algorithm": "full_page"}}],
    )
    session.add_all([item, src])
    await session.flush()
    session.add(InfoItemSource(info_item_id=item.info_item_id, info_source_id=src.info_source_id))
    _seed_status(session, item)
    await session.flush()

    r = await client.get(
        f"/dashboard/info-items/{item.info_item_id}/watcher-section",
        headers=_HEADERS,
    )
    assert r.status_code == 200
    assert "toggle-watch-active" in r.text


@pytest.mark.asyncio
async def test_toggle_succeeds_even_when_watcher_would_reject_it(client, session):
    """The archived-item guard is gone, deliberately (archiver#158).

    Watcher used to 409 pause/resume on an archived WatchedItem. Archiver has no
    local archived state, and the design settled that a Watcher-local pause is
    reverted by reconciliation — archive is mechanism, not policy, like
    ``domain_suspended``. So the write lands and the divergence surfaces as
    ``applied_active != active`` on the return leg instead of a silent rejection.
    """
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
    assert "showFlash" not in r.headers.get("HX-Trigger", "")
    await session.refresh(item)
    assert item.watch_active is False


@pytest.mark.asyncio
async def test_toggle_local_write_failure_degrades_with_a_flash(client, session, monkeypatch):
    """A failed local write flashes and re-renders rather than 500ing — the
    #151 precedent, now applied to a fault that is ours rather than Watcher's."""
    watcher = _mock_watcher(_wi("ok"))
    app.dependency_overrides[get_watcher_client] = lambda: watcher
    item = InfoItem(name="toggle flash", watcher_item_id=_WI_ID)
    session.add(item)
    await session.flush()

    async def _boom(*_a, **_kw):
        raise RuntimeError("outbox insert failed")

    monkeypatch.setattr(dash_items, "announce_info_item", _boom)

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/toggle-watch-active",
        headers=_HEADERS,
        data={"active": "false"},
    )
    assert r.status_code == 200
    hx = r.headers.get("HX-Trigger", "")
    assert "showFlash" in hx
    assert '"level": "error"' in hx


# ---------------------------------------------------------------------------
# GET /watcher-status — the drift line renders (CR round 2, finding 13)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_watcher_status_renders_drift_badge(client, session):
    """Announced ahead of applied is the detector's whole purpose."""
    app.dependency_overrides[get_watcher_client] = lambda: _mock_watcher()
    item = InfoItem(name="drifting item", watcher_item_id=_WI_ID, announcement_generation=9)
    session.add(item)
    await session.flush()
    _seed_status(session, item, applied_generation=7)
    await session.flush()

    r = await client.get(
        f"/dashboard/info-items/{item.info_item_id}/watcher-status",
        headers=_HEADERS,
    )
    assert r.status_code == 200
    assert "9 announced" in r.text
    assert "7 applied" in r.text
    assert "drift" in r.text


@pytest.mark.asyncio
async def test_watcher_status_renders_ahead_of_registry_badge(client, session):
    """Applied *ahead* of announced is an anomaly, not health — and Jinja
    renders an undefined attribute as empty, so only a render-level assertion
    catches a typo in the template's context key."""
    app.dependency_overrides[get_watcher_client] = lambda: _mock_watcher()
    item = InfoItem(name="ahead item", watcher_item_id=_WI_ID, announcement_generation=5)
    session.add(item)
    await session.flush()
    _seed_status(session, item, applied_generation=7)
    await session.flush()

    r = await client.get(
        f"/dashboard/info-items/{item.info_item_id}/watcher-status",
        headers=_HEADERS,
    )
    assert r.status_code == 200
    assert "ahead of registry" in r.text
    assert "drift" not in r.text  # not the same condition


@pytest.mark.asyncio
async def test_watcher_section_renders_ahead_of_registry_badge(client, session):
    """Both partials carry the badge; both need the assertion."""
    app.dependency_overrides[get_watcher_client] = lambda: _mock_watcher()
    item = InfoItem(name="ahead section item", watcher_item_id=_WI_ID, announcement_generation=5)
    session.add(item)
    await session.flush()
    _seed_status(session, item, applied_generation=7)
    await session.flush()

    r = await client.get(
        f"/dashboard/info-items/{item.info_item_id}/watcher-section",
        headers=_HEADERS,
    )
    assert r.status_code == 200
    assert "ahead of registry" in r.text
