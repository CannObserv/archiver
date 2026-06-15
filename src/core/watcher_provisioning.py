"""Best-effort Watcher provisioning helpers.

Called post-commit from API routes. All functions swallow exceptions and log
on failure — they never propagate errors to the caller.

All three functions accept ``watcher: WatcherClient | None``; a None value
means WATCHER_BASE_URL / WATCHER_API_KEY are unset and all calls are no-ops.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.core.logging import get_logger
from src.core.models import InfoItem, InfoItemSource, InfoSource

if TYPE_CHECKING:
    from watcher_client import WatcherClient

logger = get_logger(__name__)


async def provision_on_create(
    session: AsyncSession,
    watcher: WatcherClient | None,
    item: InfoItem,
    info_source: InfoSource,
    schedule_config: dict | None = None,
    is_active: bool | None = None,
) -> None:
    """Provision a WatchedItem for a newly created InfoItem + primary InfoSource.

    On success, stores the Watcher-allocated WatchedItem ID on ``item`` and
    commits. On any failure, logs and returns without raising. ``schedule_config``
    (e.g. ``{"interval": "1d"}``) sets the per-item fetch cadence; None lets
    Watcher apply its default. ``is_active`` provisions the item active (``True``)
    or paused (``False``); None lets Watcher apply its default (active).
    """
    if watcher is None:
        return
    try:
        result = await watcher.provision_watched_item(
            url=info_source.url,
            source_specs=list(info_source.source_specs),
            info_item_id=str(item.info_item_id),
            archiver_info_source_id=str(info_source.info_source_id),
            schedule_config=schedule_config,
            is_active=is_active,
        )
        item.watcher_item_id = str(result.id)
        await session.commit()
    except Exception:
        logger.exception("Watcher provisioning failed for InfoItem %s", item.info_item_id)


async def sync_on_source_swap(
    session: AsyncSession,
    watcher: WatcherClient | None,
    info_item: InfoItem,
    new_info_source: InfoSource,
) -> None:
    """Push updated URL, specs, and source ID to Watcher after a primary swap.

    No-op when the InfoItem has no ``watcher_item_id`` (pre-integration item or
    provisioning was never attempted). The "Begin watching" dashboard affordance
    handles on-demand provisioning in that case.
    """
    if watcher is None or not info_item.watcher_item_id:
        return
    try:
        await watcher.patch_watched_item(
            info_item.watcher_item_id,
            effective_url=new_info_source.url,
            source_specs=list(new_info_source.source_specs),
            archiver_info_source_id=str(new_info_source.info_source_id),
        )
    except Exception:
        logger.exception(
            "Watcher sync failed for InfoItem %s after primary source swap",
            info_item.info_item_id,
        )


async def sync_on_spec_update(
    session: AsyncSession,
    watcher: WatcherClient | None,
    info_source_id: ULID,
    new_source_specs: list[dict],
) -> None:
    """Push updated specs to Watcher for all InfoItems using this source as their primary.

    Queries InfoItems with an active binding to ``info_source_id`` that have a
    ``watcher_item_id``. Each is patched independently; failures are logged per-item.
    """
    if watcher is None:
        return
    result = await session.execute(
        select(InfoItem)
        .join(InfoItemSource, InfoItemSource.info_item_id == InfoItem.info_item_id)
        .where(
            InfoItemSource.info_source_id == info_source_id,
            InfoItemSource.deactivated_at.is_(None),
            InfoItem.watcher_item_id.isnot(None),
        )
    )
    items = result.scalars().all()
    for item in items:
        try:
            await watcher.patch_watched_item(
                item.watcher_item_id,  # type: ignore[arg-type]
                source_specs=new_source_specs,
            )
        except Exception:
            logger.exception("Watcher spec sync failed for InfoItem %s", item.info_item_id)
