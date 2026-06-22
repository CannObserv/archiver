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
from src.core.models import InfoItem, InfoItemSource, InfoSource
from src.dashboard.routes.info_items import _clear_stale_watcher_link

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


# ---------------------------------------------------------------------------
# POST /resync-watcher — 404 self-heals to not_watching (CR #64 finding 2)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resync_watcher_404_clears_link_and_shows_not_watching(client, session):
    """resync routes the 404 through sync_on_source_swap (swallowed to FAILED); the
    trailing status re-render then re-fetches, 404s, and reconciles to not_watching.
    The flash stays generic ("unavailable") — only the self-heal is asserted here.
    """
    app.dependency_overrides[get_watcher_client] = lambda: _watcher_404()
    item = InfoItem(name="resync-404", watcher_item_id=_WI_ID)
    src = InfoSource(url="https://example.com/resync-404", source_specs=[])
    session.add_all([item, src])
    await session.flush()
    session.add(InfoItemSource(info_item_id=item.info_item_id, info_source_id=src.info_source_id))
    await session.flush()

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/resync-watcher",
        headers=_HEADERS,
    )
    assert r.status_code == 200
    assert "Not watching" in r.text

    await session.refresh(item)
    assert item.watcher_item_id is None


# ---------------------------------------------------------------------------
# Reconcile-commit failure is best-effort: never raises, never 500s the partial,
# and retains the link for a later retry (CR #64 finding 1)
# ---------------------------------------------------------------------------


async def _boom() -> None:
    raise RuntimeError("db connection dropped")


@pytest.mark.asyncio
async def test_clear_stale_watcher_link_returns_false_when_commit_fails(session, monkeypatch):
    """A failed reconcile commit is swallowed: returns False, never raises, and the
    link is left intact so the caller keeps degrading instead of 500ing."""
    item = InfoItem(name="clear-commit-fail", watcher_item_id=_WI_ID)
    session.add(item)
    await session.commit()  # durable so the helper's rollback preserves the row

    monkeypatch.setattr(session, "commit", _boom)

    result = await _clear_stale_watcher_link(session, item)

    assert result is False
    # item remains usable and the link was not durably cleared
    assert item.watcher_item_id == _WI_ID


@pytest.mark.asyncio
async def test_watcher_section_404_commit_failure_stays_degraded_and_retains_link(
    client, session, monkeypatch
):
    """When clearing the stale link can't commit, the partial degrades (200) rather
    than 500ing, and the link survives for the next read to retry."""
    app.dependency_overrides[get_watcher_client] = lambda: _watcher_404()
    item = InfoItem(name="section-404-commitfail", watcher_item_id=_WI_ID)
    session.add(item)
    await session.commit()  # durable so the helper's rollback preserves the row

    monkeypatch.setattr(session, "commit", _boom)

    r = await client.get(
        f"/dashboard/info-items/{item.info_item_id}/watcher-section",
        headers=_HEADERS,
    )
    assert r.status_code == 200
    assert "Watcher unavailable" in r.text
    assert "Not watching" not in r.text
    assert item.watcher_item_id == _WI_ID
