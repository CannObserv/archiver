"""Tests for the Section 3 Watcher panel (GET /watcher-section) and
HX-Trigger header on check-now / resync-watcher.

Covers:
  GET  /dashboard/info-items/{id}/watcher-section
  HX-Trigger: watcherUpdated on POST /check-now
  HX-Trigger: watcherUpdated on POST /resync-watcher
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from watcher_client import WatchedItemResponse

from src.api.deps import get_watcher_client
from src.api.main import app
from src.core.models import InfoItem, InfoItemSource, InfoSource

_HEADERS = {"X-ExeDev-UserID": "ext-section", "X-ExeDev-Email": "section@example.com"}
_WI_ID = "01HZZWATCHER00000000000001"
_TS = "2026-06-11T12:00:00+00:00"
_BASE_URL = "https://watcher.example.com"


def _wi(
    health: str = "ok",
    last_checked_at: str | None = _TS,
    effective_url: str = "https://example.com/page",
    source_specs: list | None = None,
) -> WatchedItemResponse:
    return WatchedItemResponse.from_dict(
        {
            "id": _WI_ID,
            "name": "Test Item",
            "description": None,
            "is_active": True,
            "archived_at": None,
            "last_reviewed_at": None,
            "last_checked_at": last_checked_at,
            "last_changed_at": None,
            "health_status": health,
            "default_schedule_config": None,
            "default_content_type": None,
            "default_tags": None,
            "effective_url": effective_url,
            "source_specs": source_specs or [],
            "created_at": _TS,
            "updated_at": _TS,
        }
    )


def _mock_watcher(wi: WatchedItemResponse | None = None, base_url: str = _BASE_URL) -> MagicMock:
    m = MagicMock()
    m.base_url = base_url
    m.get_watched_item = AsyncMock(return_value=wi or _wi())
    m.check_now = AsyncMock(return_value=wi or _wi())
    m.patch_watched_item = AsyncMock(return_value=wi or _wi())
    return m


@pytest.fixture(autouse=True)
def _clear_watcher_override():
    yield
    app.dependency_overrides.pop(get_watcher_client, None)


# ---------------------------------------------------------------------------
# GET /watcher-section — not configured
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_watcher_section_not_configured(client, session):
    app.dependency_overrides[get_watcher_client] = lambda: None
    item = InfoItem(name="section-not-configured")
    session.add(item)
    await session.flush()

    r = await client.get(
        f"/dashboard/info-items/{item.info_item_id}/watcher-section",
        headers=_HEADERS,
    )
    assert r.status_code == 200
    assert "watcher-section" in r.text
    assert "not configured" in r.text.lower()


# ---------------------------------------------------------------------------
# GET /watcher-section — not watching (watcher_item_id IS NULL)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_watcher_section_not_watching(client, session):
    app.dependency_overrides[get_watcher_client] = lambda: _mock_watcher()
    item = InfoItem(name="section-not-watching", watcher_item_id=None)
    session.add(item)
    await session.flush()

    r = await client.get(
        f"/dashboard/info-items/{item.info_item_id}/watcher-section",
        headers=_HEADERS,
    )
    assert r.status_code == 200
    assert "Not watching" in r.text
    assert "begin-watching" in r.text


# ---------------------------------------------------------------------------
# GET /watcher-section — watching (ok health, effective_url, view-in-watcher link)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_watcher_section_watching_shows_details(client, session):
    wi = _wi("ok", effective_url="https://example.com/page")
    watcher = _mock_watcher(wi, base_url=_BASE_URL)
    app.dependency_overrides[get_watcher_client] = lambda: watcher

    item = InfoItem(name="section-watching", watcher_item_id=_WI_ID)
    session.add(item)
    await session.flush()

    r = await client.get(
        f"/dashboard/info-items/{item.info_item_id}/watcher-section",
        headers=_HEADERS,
    )
    assert r.status_code == 200
    assert "watcher-section" in r.text
    # Health badge
    assert "OK" in r.text
    # Effective URL
    assert "https://example.com/page" in r.text
    # View-in-Watcher deeplink
    assert _WI_ID in r.text
    assert _BASE_URL in r.text
    # Action buttons
    assert "check-now" in r.text
    assert "resync-watcher" in r.text


# ---------------------------------------------------------------------------
# GET /watcher-section — degraded (Watcher raises WatcherError)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_watcher_section_degraded(client, session):
    from watcher_client import WatcherError

    watcher = MagicMock()
    watcher.base_url = _BASE_URL
    watcher.get_watched_item = AsyncMock(side_effect=WatcherError("timeout"))
    app.dependency_overrides[get_watcher_client] = lambda: watcher

    item = InfoItem(name="section-degraded", watcher_item_id=_WI_ID)
    session.add(item)
    await session.flush()

    r = await client.get(
        f"/dashboard/info-items/{item.info_item_id}/watcher-section",
        headers=_HEADERS,
    )
    assert r.status_code == 200
    assert "unavailable" in r.text.lower()


# ---------------------------------------------------------------------------
# GET /watcher-section — spec summary rendered
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_watcher_section_shows_spec_summary(client, session):
    specs = [
        {
            "schema_version": 1,
            "extraction": {"algorithm": "css", "selector": "h1"},
            "fingerprint": {},
        },  # noqa: E501
        {
            "schema_version": 1,
            "extraction": {"algorithm": "css", "selector": ".body"},
            "fingerprint": {},
        },  # noqa: E501
    ]
    wi = _wi("ok", source_specs=specs)
    watcher = _mock_watcher(wi)
    app.dependency_overrides[get_watcher_client] = lambda: watcher

    item = InfoItem(name="section-spec-summary", watcher_item_id=_WI_ID)
    session.add(item)
    await session.flush()

    r = await client.get(
        f"/dashboard/info-items/{item.info_item_id}/watcher-section",
        headers=_HEADERS,
    )
    assert r.status_code == 200
    # Summary should show algorithm name
    assert "css" in r.text.lower()


# ---------------------------------------------------------------------------
# GET /watcher-section — partial carries hx-trigger for auto-refresh
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_watcher_section_carries_auto_refresh_trigger(client, session):
    watcher = _mock_watcher(_wi("ok"))
    app.dependency_overrides[get_watcher_client] = lambda: watcher

    item = InfoItem(name="section-auto-refresh", watcher_item_id=_WI_ID)
    session.add(item)
    await session.flush()

    r = await client.get(
        f"/dashboard/info-items/{item.info_item_id}/watcher-section",
        headers=_HEADERS,
    )
    assert r.status_code == 200
    assert "watcherUpdated" in r.text


# ---------------------------------------------------------------------------
# POST /check-now — response includes HX-Trigger: watcherUpdated
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_now_triggers_watcher_updated(client, session):
    watcher = _mock_watcher(_wi("ok"))
    app.dependency_overrides[get_watcher_client] = lambda: watcher

    item = InfoItem(name="check-now-trigger", watcher_item_id=_WI_ID)
    session.add(item)
    await session.flush()

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/check-now",
        headers=_HEADERS,
    )
    assert r.status_code == 200
    hx_trigger = r.headers.get("HX-Trigger", "")
    assert "watcherUpdated" in hx_trigger


# ---------------------------------------------------------------------------
# POST /resync-watcher — response includes HX-Trigger: watcherUpdated
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resync_watcher_triggers_watcher_updated(client, session):
    watcher = _mock_watcher(_wi("ok"))
    app.dependency_overrides[get_watcher_client] = lambda: watcher

    item = InfoItem(name="resync-trigger", watcher_item_id=_WI_ID)
    src = InfoSource(url="https://example.com/resync-trigger", source_specs=[])
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
    hx_trigger = r.headers.get("HX-Trigger", "")
    assert "watcherUpdated" in hx_trigger
