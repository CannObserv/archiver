"""Self-heal a stale watcher_item_id when Watcher reports the WatchedItem gone (404).

A permanently deleted WatchedItem 404s on every read. Archiver must distinguish
that from a transient outage: on a confirmed 404 it clears watcher_item_id and
falls back to the not_watching state (re-exposing "Begin Watching") instead of
sticking in degraded forever. Transient failures (network/5xx) still render
degraded and retain the id, so a brief outage never drops the link.

Covers:
  GET  /watcher-section        404 -> not_watching, link cleared
  GET  /watcher-status         404 -> not_watching, link cleared
  GET  /watcher-section        network error -> degraded, link retained (regression)
  POST /check-now              404 -> not_watching + "no longer watched" flash, link cleared
  POST /toggle-watch-active    404 -> not_watching + "no longer watched" flash, link cleared
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from watcher_client.errors import WatcherNotFound

from src.api.deps import get_watcher_client
from src.api.main import app
from src.core.models import InfoItem

_HEADERS = {"X-ExeDev-UserID": "ext-404", "X-ExeDev-Email": "reconcile@example.com"}
_WI_ID = "01HZZWATCHER00000000000009"


def _watcher_404() -> MagicMock:
    """A WatcherClient mock whose reads/actions all 404 (deleted WatchedItem)."""
    m = MagicMock()
    m.base_url = "https://watcher.example.com"
    err = WatcherNotFound("WatchedItem not found", status_code=404)
    m.get_watched_item = AsyncMock(side_effect=err)
    m.check_now = AsyncMock(side_effect=err)
    m.patch_watched_item = AsyncMock(side_effect=err)
    return m


def _watcher_down() -> MagicMock:
    """A WatcherClient mock that fails with a transient (non-404) error."""
    m = MagicMock()
    m.base_url = "https://watcher.example.com"
    m.get_watched_item = AsyncMock(side_effect=Exception("connection refused"))
    return m


# ---------------------------------------------------------------------------
# GET /watcher-section — 404 self-heals to not_watching and clears the link
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_watcher_section_404_clears_link_and_shows_not_watching(client, session):
    app.dependency_overrides[get_watcher_client] = lambda: _watcher_404()
    item = InfoItem(name="section-404", watcher_item_id=_WI_ID)
    session.add(item)
    await session.flush()

    r = await client.get(
        f"/dashboard/info-items/{item.info_item_id}/watcher-section",
        headers=_HEADERS,
    )
    assert r.status_code == 200
    assert "Not watching" in r.text
    assert "begin-watching" in r.text
    assert "Watcher unavailable" not in r.text

    await session.refresh(item)
    assert item.watcher_item_id is None


# ---------------------------------------------------------------------------
# GET /watcher-status — 404 self-heals to not_watching and clears the link
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_watcher_status_404_clears_link_and_shows_not_watching(client, session):
    app.dependency_overrides[get_watcher_client] = lambda: _watcher_404()
    item = InfoItem(name="status-404", watcher_item_id=_WI_ID)
    session.add(item)
    await session.flush()

    r = await client.get(
        f"/dashboard/info-items/{item.info_item_id}/watcher-status",
        headers=_HEADERS,
    )
    assert r.status_code == 200
    assert "Not watching" in r.text
    assert "begin-watching" in r.text

    await session.refresh(item)
    assert item.watcher_item_id is None


# ---------------------------------------------------------------------------
# GET /watcher-section — transient failure stays degraded and retains the link
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_watcher_section_transient_error_stays_degraded_and_retains_link(client, session):
    app.dependency_overrides[get_watcher_client] = lambda: _watcher_down()
    item = InfoItem(name="section-down", watcher_item_id=_WI_ID)
    session.add(item)
    await session.flush()

    r = await client.get(
        f"/dashboard/info-items/{item.info_item_id}/watcher-section",
        headers=_HEADERS,
    )
    assert r.status_code == 200
    assert "Watcher unavailable" in r.text
    assert "Not watching" not in r.text

    await session.refresh(item)
    assert item.watcher_item_id == _WI_ID


# ---------------------------------------------------------------------------
# POST /check-now — 404 self-heals to not_watching with an accurate flash
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_now_404_clears_link_and_flashes_removed(client, session):
    app.dependency_overrides[get_watcher_client] = lambda: _watcher_404()
    item = InfoItem(name="check-now-404", watcher_item_id=_WI_ID)
    session.add(item)
    await session.flush()

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/check-now",
        headers=_HEADERS,
    )
    assert r.status_code == 200
    assert "Not watching" in r.text
    hx_trigger = r.headers.get("HX-Trigger", "")
    assert "showFlash" in hx_trigger
    assert "no longer watched" in hx_trigger

    await session.refresh(item)
    assert item.watcher_item_id is None


# ---------------------------------------------------------------------------
# POST /toggle-watch-active — 404 self-heals to not_watching with an accurate flash
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_toggle_watch_active_404_clears_link_and_flashes_removed(client, session):
    app.dependency_overrides[get_watcher_client] = lambda: _watcher_404()
    item = InfoItem(name="toggle-404", watcher_item_id=_WI_ID)
    session.add(item)
    await session.flush()

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/toggle-watch-active",
        headers=_HEADERS,
        data={"active": "false"},
    )
    assert r.status_code == 200
    assert "Not watching" in r.text
    hx_trigger = r.headers.get("HX-Trigger", "")
    assert "showFlash" in hx_trigger
    assert "no longer watched" in hx_trigger

    await session.refresh(item)
    assert item.watcher_item_id is None
