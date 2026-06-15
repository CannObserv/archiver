"""Unit tests for watcher provisioning helpers (src/core/watcher_provisioning.py).

Uses a real DB session (via fixtures) plus a mock WatcherClient.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from watcher_client import WatchedItemResponse

from src.core.models import InfoItem, InfoItemSource, InfoSource
from src.core.watcher_provisioning import (
    WatcherSyncOutcome,
    provision_on_create,
    sync_on_source_swap,
    sync_on_spec_update,
)

_TS = "2026-06-10T00:00:00+00:00"
_WI_ID = "01HZZWATCHER00000000000001"


def _wi(wi_id: str = _WI_ID) -> WatchedItemResponse:
    return WatchedItemResponse.from_dict(
        {
            "id": wi_id,
            "name": "Test",
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
            "effective_url": "https://example.com/",
            "source_specs": [],
            "created_at": _TS,
            "updated_at": _TS,
        }
    )


def _mock_watcher(wi: WatchedItemResponse = None) -> MagicMock:
    watcher = MagicMock()
    watcher.provision_watched_item = AsyncMock(return_value=wi or _wi())
    watcher.patch_watched_item = AsyncMock(return_value=wi or _wi())
    return watcher


# ---------------------------------------------------------------------------
# provision_on_create
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_provision_on_create_sets_watcher_item_id(session):
    item = InfoItem(name="test item")
    src = InfoSource(url="https://example.com/", source_specs=[])
    session.add(item)
    session.add(src)
    await session.flush()

    watcher = _mock_watcher(_wi(_WI_ID))
    outcome = await provision_on_create(session, watcher, item, src)

    assert outcome is WatcherSyncOutcome.OK
    assert item.watcher_item_id == _WI_ID
    watcher.provision_watched_item.assert_awaited_once_with(
        url="https://example.com/",
        source_specs=[],
        info_item_id=str(item.info_item_id),
        archiver_info_source_id=str(src.info_source_id),
        schedule_config=None,
        is_active=None,
    )


@pytest.mark.asyncio
async def test_provision_on_create_forwards_schedule_config(session):
    item = InfoItem(name="test item")
    src = InfoSource(url="https://example.com/", source_specs=[])
    session.add(item)
    session.add(src)
    await session.flush()

    watcher = _mock_watcher(_wi(_WI_ID))
    await provision_on_create(session, watcher, item, src, schedule_config={"interval": "6h"})

    watcher.provision_watched_item.assert_awaited_once_with(
        url="https://example.com/",
        source_specs=[],
        info_item_id=str(item.info_item_id),
        archiver_info_source_id=str(src.info_source_id),
        schedule_config={"interval": "6h"},
        is_active=None,
    )


@pytest.mark.asyncio
async def test_provision_on_create_forwards_is_active(session):
    item = InfoItem(name="test item")
    src = InfoSource(url="https://example.com/", source_specs=[])
    session.add(item)
    session.add(src)
    await session.flush()

    watcher = _mock_watcher(_wi(_WI_ID))
    await provision_on_create(session, watcher, item, src, is_active=False)

    watcher.provision_watched_item.assert_awaited_once_with(
        url="https://example.com/",
        source_specs=[],
        info_item_id=str(item.info_item_id),
        archiver_info_source_id=str(src.info_source_id),
        schedule_config=None,
        is_active=False,
    )


@pytest.mark.asyncio
async def test_provision_on_create_none_watcher_is_noop(session):
    item = InfoItem(name="test item")
    src = InfoSource(url="https://example.com/", source_specs=[])
    session.add(item)
    session.add(src)
    await session.flush()

    outcome = await provision_on_create(session, None, item, src)

    assert outcome is WatcherSyncOutcome.SKIPPED
    assert item.watcher_item_id is None


@pytest.mark.asyncio
async def test_provision_on_create_watcher_error_does_not_raise(session):
    item = InfoItem(name="test item")
    src = InfoSource(url="https://example.com/", source_specs=[])
    session.add(item)
    session.add(src)
    await session.flush()

    watcher = MagicMock()
    watcher.provision_watched_item = AsyncMock(side_effect=Exception("Watcher down"))

    # Must not raise
    outcome = await provision_on_create(session, watcher, item, src)

    assert outcome is WatcherSyncOutcome.FAILED
    assert item.watcher_item_id is None


@pytest.mark.asyncio
async def test_provision_on_create_adopts_existing_on_conflict(session):
    """409 from Watcher (WatchedItem already exists) → adopt its ID rather than fail.

    Reproduces the state-desync bug: a WatchedItem exists in Watcher but the
    InfoItem's watcher_item_id is NULL (e.g. a pre-#55 item). Provisioning 409s;
    we recover by looking up the existing WatchedItem and adopting its ID.
    """
    from watcher_client.errors import WatcherConflict

    item = InfoItem(name="desynced item", watcher_item_id=None)
    src = InfoSource(url="https://example.com/", source_specs=[])
    session.add(item)
    session.add(src)
    await session.flush()

    watcher = MagicMock()
    watcher.provision_watched_item = AsyncMock(side_effect=WatcherConflict("already exists"))
    watcher.get_by_info_item_id = AsyncMock(return_value=_wi(_WI_ID))

    outcome = await provision_on_create(session, watcher, item, src)

    assert outcome is WatcherSyncOutcome.OK
    assert item.watcher_item_id == _WI_ID
    watcher.get_by_info_item_id.assert_awaited_once_with(str(item.info_item_id))


@pytest.mark.asyncio
async def test_provision_on_create_conflict_without_existing_is_failed(session):
    """409 but lookup finds nothing → genuine failure (don't pretend success)."""
    from watcher_client.errors import WatcherConflict

    item = InfoItem(name="conflict-no-existing", watcher_item_id=None)
    src = InfoSource(url="https://example.com/", source_specs=[])
    session.add(item)
    session.add(src)
    await session.flush()

    watcher = MagicMock()
    watcher.provision_watched_item = AsyncMock(side_effect=WatcherConflict("already exists"))
    watcher.get_by_info_item_id = AsyncMock(return_value=None)

    outcome = await provision_on_create(session, watcher, item, src)

    assert outcome is WatcherSyncOutcome.FAILED
    assert item.watcher_item_id is None


# ---------------------------------------------------------------------------
# sync_on_source_swap
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_on_source_swap_calls_patch(session):
    item = InfoItem(name="test", watcher_item_id=_WI_ID)
    src = InfoSource(url="https://example.com/new", source_specs=[{"schema_version": 1}])
    session.add(item)
    session.add(src)
    await session.flush()

    watcher = _mock_watcher()
    outcome = await sync_on_source_swap(session, watcher, item, src)

    assert outcome is WatcherSyncOutcome.OK
    watcher.patch_watched_item.assert_awaited_once_with(
        _WI_ID,
        effective_url="https://example.com/new",
        source_specs=[{"schema_version": 1}],
        archiver_info_source_id=str(src.info_source_id),
    )


@pytest.mark.asyncio
async def test_sync_on_source_swap_no_watcher_item_id_is_noop(session):
    item = InfoItem(name="test", watcher_item_id=None)
    src = InfoSource(url="https://example.com/", source_specs=[])
    session.add(item)
    session.add(src)
    await session.flush()

    watcher = _mock_watcher()
    outcome = await sync_on_source_swap(session, watcher, item, src)

    assert outcome is WatcherSyncOutcome.SKIPPED
    watcher.patch_watched_item.assert_not_awaited()


@pytest.mark.asyncio
async def test_sync_on_source_swap_none_watcher_is_noop(session):
    item = InfoItem(name="test", watcher_item_id=_WI_ID)
    src = InfoSource(url="https://example.com/", source_specs=[])
    session.add(item)
    session.add(src)
    await session.flush()

    outcome = await sync_on_source_swap(session, None, item, src)

    assert outcome is WatcherSyncOutcome.SKIPPED


@pytest.mark.asyncio
async def test_sync_on_source_swap_error_does_not_raise(session):
    item = InfoItem(name="test", watcher_item_id=_WI_ID)
    src = InfoSource(url="https://example.com/", source_specs=[])
    session.add(item)
    session.add(src)
    await session.flush()

    watcher = MagicMock()
    watcher.patch_watched_item = AsyncMock(side_effect=Exception("Watcher down"))

    outcome = await sync_on_source_swap(session, watcher, item, src)

    assert outcome is WatcherSyncOutcome.FAILED


# ---------------------------------------------------------------------------
# sync_on_spec_update
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_on_spec_update_patches_linked_item(session):
    item = InfoItem(name="test", watcher_item_id=_WI_ID)
    src = InfoSource(url="https://example.com/", source_specs=[])
    session.add(item)
    session.add(src)
    await session.flush()
    session.add(InfoItemSource(info_item_id=item.info_item_id, info_source_id=src.info_source_id))
    await session.flush()

    new_specs = [{"schema_version": 1, "extraction": {"algorithm": "full_page"}}]
    watcher = _mock_watcher()
    await sync_on_spec_update(session, watcher, src.info_source_id, new_specs)

    watcher.patch_watched_item.assert_awaited_once_with(_WI_ID, source_specs=new_specs)


@pytest.mark.asyncio
async def test_sync_on_spec_update_skips_item_without_watcher_id(session):
    item = InfoItem(name="test", watcher_item_id=None)
    src = InfoSource(url="https://example.com/", source_specs=[])
    session.add(item)
    session.add(src)
    await session.flush()
    session.add(InfoItemSource(info_item_id=item.info_item_id, info_source_id=src.info_source_id))
    await session.flush()

    watcher = _mock_watcher()
    await sync_on_spec_update(session, watcher, src.info_source_id, [])

    watcher.patch_watched_item.assert_not_awaited()


@pytest.mark.asyncio
async def test_sync_on_spec_update_none_watcher_is_noop(session):
    src = InfoSource(url="https://example.com/", source_specs=[])
    session.add(src)
    await session.flush()

    await sync_on_spec_update(session, None, src.info_source_id, [])


@pytest.mark.asyncio
async def test_sync_on_spec_update_error_does_not_raise(session):
    item = InfoItem(name="test", watcher_item_id=_WI_ID)
    src = InfoSource(url="https://example.com/", source_specs=[])
    session.add(item)
    session.add(src)
    await session.flush()
    session.add(InfoItemSource(info_item_id=item.info_item_id, info_source_id=src.info_source_id))
    await session.flush()

    watcher = MagicMock()
    watcher.patch_watched_item = AsyncMock(side_effect=Exception("Watcher down"))

    await sync_on_spec_update(session, watcher, src.info_source_id, [])
