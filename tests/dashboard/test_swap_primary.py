"""Tests for swap-primary-source and swap-primary-by-id dashboard endpoints.

Covers:
  POST /dashboard/info-items/{id}/swap-primary-source  — author new source inline
  POST /dashboard/info-items/{id}/swap-primary-by-id   — bind existing source by ULID
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select
from watcher_client import WatchedItemResponse

from src.api.deps import get_watcher_client
from src.api.main import app
from src.core.models import InfoItem, InfoItemSource, InfoSource

_HEADERS = {"X-ExeDev-UserID": "ext-swap", "X-ExeDev-Email": "swap@example.com"}
_WI_ID = "01HZZWATCHER00000000000001"
_TS = "2026-06-11T12:00:00+00:00"
_SPEC = '[{"schema_version":1,"extraction":{"algorithm":"full_page"},"fingerprint":{}}]'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _wi() -> WatchedItemResponse:
    return WatchedItemResponse.from_dict(
        {
            "id": _WI_ID,
            "name": "Test",
            "description": None,
            "is_active": True,
            "archived_at": None,
            "last_reviewed_at": None,
            "last_checked_at": _TS,
            "last_changed_at": None,
            "health_status": "ok",
            "default_schedule_config": None,
            "default_content_type": None,
            "default_tags": None,
            "effective_url": "https://example.com/",
            "source_specs": [],
            "created_at": _TS,
            "updated_at": _TS,
        }
    )


def _mock_watcher() -> MagicMock:
    m = MagicMock()
    m.patch_watched_item = AsyncMock(return_value=_wi())
    m.provision_watched_item = AsyncMock(return_value=_wi())
    return m


@pytest.fixture(autouse=True)
def _clear_watcher_override():
    """Ensure get_watcher_client override is removed after each test."""
    yield
    app.dependency_overrides.pop(get_watcher_client, None)


# ---------------------------------------------------------------------------
# POST /swap-primary-source — new source created + bound
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_swap_primary_source_creates_binding(client, session):
    """New InfoSource created and bound as active primary."""
    app.dependency_overrides[get_watcher_client] = lambda: None
    item = InfoItem(name="swap-creates")
    src_old = InfoSource(url="https://old.swap-creates.example.com/", source_specs=[])
    session.add(item)
    session.add(src_old)
    await session.flush()
    session.add(
        InfoItemSource(
            info_item_id=item.info_item_id,
            info_source_id=src_old.info_source_id,
        )
    )
    await session.commit()

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/swap-primary-source",
        data={"url": "https://new.swap-creates.example.com/", "source_specs": _SPEC},
        headers=_HEADERS,
        follow_redirects=False,
    )
    assert r.status_code == 204
    assert f"/dashboard/info-items/{item.info_item_id}" in r.headers["HX-Redirect"]

    await session.refresh(item)
    bindings = list(
        (
            await session.execute(
                select(InfoItemSource).where(InfoItemSource.info_item_id == item.info_item_id)
            )
        )
        .scalars()
        .all()
    )
    active = [b for b in bindings if b.deactivated_at is None]
    assert len(active) == 1
    assert active[0].info_source_id != src_old.info_source_id


@pytest.mark.asyncio
async def test_swap_primary_source_deactivates_old(client, session):
    """Old active binding gains deactivated_at after swap."""
    app.dependency_overrides[get_watcher_client] = lambda: None
    item = InfoItem(name="swap-deactivates-old")
    src_old = InfoSource(url="https://old.deactivate-old.example.com/", source_specs=[])
    session.add(item)
    session.add(src_old)
    await session.flush()
    old_source_id = src_old.info_source_id
    session.add(
        InfoItemSource(
            info_item_id=item.info_item_id,
            info_source_id=old_source_id,
        )
    )
    await session.commit()

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/swap-primary-source",
        data={"url": "https://new.deactivate-old.example.com/", "source_specs": _SPEC},
        headers=_HEADERS,
        follow_redirects=False,
    )
    assert r.status_code == 204
    assert f"/dashboard/info-items/{item.info_item_id}" in r.headers["HX-Redirect"]

    old_binding = (
        await session.execute(
            select(InfoItemSource).where(
                InfoItemSource.info_item_id == item.info_item_id,
                InfoItemSource.info_source_id == old_source_id,
            )
        )
    ).scalar_one_or_none()
    assert old_binding is not None
    assert old_binding.deactivated_at is not None


@pytest.mark.asyncio
async def test_swap_primary_source_patches_watcher(client, session):
    """patch_watched_item called with new URL when watcher_item_id is set."""
    watcher = _mock_watcher()
    app.dependency_overrides[get_watcher_client] = lambda: watcher

    item = InfoItem(name="swap-patches-watcher", watcher_item_id=_WI_ID)
    src_old = InfoSource(url="https://old.patches-watcher.example.com/", source_specs=[])
    session.add(item)
    session.add(src_old)
    await session.flush()
    session.add(
        InfoItemSource(
            info_item_id=item.info_item_id,
            info_source_id=src_old.info_source_id,
        )
    )
    await session.commit()

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/swap-primary-source",
        data={"url": "https://new.patches-watcher.example.com/", "source_specs": _SPEC},
        headers=_HEADERS,
        follow_redirects=False,
    )
    assert r.status_code == 204
    assert f"/dashboard/info-items/{item.info_item_id}" in r.headers["HX-Redirect"]
    watcher.patch_watched_item.assert_awaited_once()
    call_kwargs = watcher.patch_watched_item.call_args
    assert call_kwargs.args[0] == _WI_ID
    assert call_kwargs.kwargs["effective_url"] == "https://new.patches-watcher.example.com/"


@pytest.mark.asyncio
async def test_swap_primary_source_no_watcher_no_crash(client, session):
    """Swap succeeds without error when Watcher is not configured."""
    app.dependency_overrides[get_watcher_client] = lambda: None
    item = InfoItem(name="swap-no-watcher")
    session.add(item)
    await session.commit()

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/swap-primary-source",
        data={"url": "https://fresh.no-watcher.example.com/", "source_specs": _SPEC},
        headers=_HEADERS,
        follow_redirects=False,
    )
    assert r.status_code == 204
    assert f"/dashboard/info-items/{item.info_item_id}" in r.headers["HX-Redirect"]


@pytest.mark.asyncio
async def test_swap_primary_source_invalid_url(client, session):
    """Invalid URL returns 422."""
    app.dependency_overrides[get_watcher_client] = lambda: None
    item = InfoItem(name="swap-bad-url")
    session.add(item)
    await session.commit()

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/swap-primary-source",
        data={"url": "not-a-url", "source_specs": "[]"},
        headers=_HEADERS,
    )
    assert r.status_code == 422
    assert "swap-error" in r.text
    assert "text-danger" in r.text


@pytest.mark.asyncio
async def test_swap_primary_source_invalid_specs(client, session):
    """Non-JSON source_specs returns 422."""
    app.dependency_overrides[get_watcher_client] = lambda: None
    item = InfoItem(name="swap-bad-specs")
    session.add(item)
    await session.commit()

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/swap-primary-source",
        data={"url": "https://example.com/page", "source_specs": "not-json"},
        headers=_HEADERS,
    )
    assert r.status_code == 422
    assert "swap-error" in r.text
    assert "text-danger" in r.text


# ---------------------------------------------------------------------------
# POST /swap-primary-by-id — bind existing InfoSource
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_swap_primary_by_id_binds_existing(client, session):
    """Old binding deactivated; new source becomes active primary."""
    app.dependency_overrides[get_watcher_client] = lambda: None
    item = InfoItem(name="swap-by-id-binds")
    src_old = InfoSource(url="https://old.byid.example.com/", source_specs=[])
    src_new = InfoSource(url="https://new.byid.example.com/", source_specs=[])
    session.add_all([item, src_old, src_new])
    await session.flush()
    session.add(
        InfoItemSource(
            info_item_id=item.info_item_id,
            info_source_id=src_old.info_source_id,
        )
    )
    await session.commit()
    new_id = src_new.info_source_id

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/swap-primary-by-id",
        data={"info_source_id": str(new_id)},
        headers=_HEADERS,
        follow_redirects=False,
    )
    assert r.status_code == 204
    assert f"/dashboard/info-items/{item.info_item_id}" in r.headers["HX-Redirect"]

    bindings = list(
        (
            await session.execute(
                select(InfoItemSource).where(InfoItemSource.info_item_id == item.info_item_id)
            )
        )
        .scalars()
        .all()
    )
    active = [b for b in bindings if b.deactivated_at is None]
    assert len(active) == 1
    assert active[0].info_source_id == new_id


@pytest.mark.asyncio
async def test_swap_primary_by_id_patches_watcher(client, session):
    """patch_watched_item called with new URL and specs on by-ID swap."""
    watcher = _mock_watcher()
    app.dependency_overrides[get_watcher_client] = lambda: watcher

    item = InfoItem(name="swap-by-id-watcher", watcher_item_id=_WI_ID)
    src_old = InfoSource(url="https://old.byid-w.example.com/", source_specs=[])
    src_new = InfoSource(
        url="https://new.byid-w.example.com/",
        source_specs=[{"schema_version": 1}],
    )
    session.add_all([item, src_old, src_new])
    await session.flush()
    session.add(
        InfoItemSource(
            info_item_id=item.info_item_id,
            info_source_id=src_old.info_source_id,
        )
    )
    await session.commit()

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/swap-primary-by-id",
        data={"info_source_id": str(src_new.info_source_id)},
        headers=_HEADERS,
        follow_redirects=False,
    )
    assert r.status_code == 204
    assert f"/dashboard/info-items/{item.info_item_id}" in r.headers["HX-Redirect"]
    watcher.patch_watched_item.assert_awaited_once()
    call_kwargs = watcher.patch_watched_item.call_args
    assert call_kwargs.args[0] == _WI_ID
    assert call_kwargs.kwargs["effective_url"] == "https://new.byid-w.example.com/"


@pytest.mark.asyncio
async def test_swap_primary_by_id_invalid_ulid(client, session):
    """Non-ULID info_source_id returns 422."""
    app.dependency_overrides[get_watcher_client] = lambda: None
    item = InfoItem(name="swap-by-id-bad-ulid")
    session.add(item)
    await session.commit()

    r = await client.post(
        f"/dashboard/info-items/{item.info_item_id}/swap-primary-by-id",
        data={"info_source_id": "not-a-ulid"},
        headers=_HEADERS,
    )
    assert r.status_code == 422
    assert "swap-by-id-error" in r.text
    assert "text-danger" in r.text
