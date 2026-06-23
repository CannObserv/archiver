"""Best-effort Watcher provisioning helpers.

Called post-commit from API routes. All functions swallow exceptions and log
on failure — they never propagate errors to the caller.

All three functions accept ``watcher: WatcherClient | None``; a None value
means WATCHER_BASE_URL / WATCHER_API_KEY are unset and all calls are no-ops.

``provision_on_create`` and ``sync_on_source_swap`` return a
:class:`WatcherSyncOutcome` so dashboard callers can flash a failure without
re-raising; ``sync_on_spec_update`` patches N items with per-item logging and
returns ``None``.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID
from watcher_client.errors import WatcherConflict, WatcherResponseError

from src.core.logging import get_logger
from src.core.models import InfoItem, InfoItemSource, InfoSource

if TYPE_CHECKING:
    from watcher_client import WatcherClient

logger = get_logger(__name__)


class WatcherSyncOutcome(StrEnum):
    """Result of a best-effort Watcher provisioning/sync call.

    Lets dashboard callers distinguish a swallowed failure from a no-op so they
    can surface an error flash only when an attempted call actually failed. The
    helpers never raise — they always return one of these.
    """

    OK = "ok"
    """The Watcher call succeeded."""

    FAILED = "failed"
    """A call was attempted and raised; the exception was logged and swallowed."""

    SKIPPED = "skipped"
    """No call was attempted (no Watcher configured or nothing to sync)."""

    CONTRACT_ERROR = "contract_error"
    """A call was attempted but the response could not be parsed
    (``WatcherResponseError``) — the watcher_client SDK is stale relative to the
    live Watcher API. Distinct from ``FAILED`` (a transport/HTTP failure) so
    callers can surface accurate, non-"try again" guidance; retrying never helps."""


async def provision_on_create(
    session: AsyncSession,
    watcher: WatcherClient | None,
    item: InfoItem,
    info_source: InfoSource,
    schedule_config: dict | None = None,
    is_active: bool | None = None,
) -> WatcherSyncOutcome:
    """Provision a WatchedItem for a newly created InfoItem + primary InfoSource.

    On success, stores the Watcher-allocated WatchedItem ID on ``item`` and
    commits. On any failure, logs and returns without raising. ``schedule_config``
    (e.g. ``{"interval": "1d"}``) sets the per-item fetch cadence; None lets
    Watcher apply its default. ``is_active`` provisions the item active (``True``)
    or paused (``False``); None lets Watcher apply its default (active).

    Returns a :class:`WatcherSyncOutcome`: ``SKIPPED`` when no Watcher is
    configured, ``OK`` on success, ``FAILED`` when the call raised (logged and
    swallowed). API-route callers may ignore the result; the dashboard uses it
    to flash provisioning failures.
    """
    if watcher is None:
        return WatcherSyncOutcome.SKIPPED
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
        return WatcherSyncOutcome.OK
    except WatcherConflict:
        # Watcher already has a WatchedItem for this InfoItem, but Archiver's
        # watcher_item_id is unset (a pre-#55 item, or a prior provision that
        # committed on Watcher but not here). Recover by adopting the existing
        # WatchedItem's ID instead of failing — otherwise "Begin watching" 409s
        # forever and the item is stuck in not_watching.
        return await _adopt_existing(session, watcher, item)
    except WatcherResponseError:
        logger.exception(
            "Watcher provisioning failed for InfoItem %s: response contract mismatch "
            "(watcher_client SDK may be stale)",
            item.info_item_id,
        )
        return WatcherSyncOutcome.CONTRACT_ERROR
    except Exception:
        logger.exception("Watcher provisioning failed for InfoItem %s", item.info_item_id)
        return WatcherSyncOutcome.FAILED


async def _adopt_existing(
    session: AsyncSession,
    watcher: WatcherClient,
    item: InfoItem,
) -> WatcherSyncOutcome:
    """Look up the WatchedItem already linked to ``item`` and store its ID.

    Used to recover from a provisioning 409. Returns ``OK`` once adopted,
    ``FAILED`` if the lookup raises or finds nothing (the conflict is then
    unexplained and we must not pretend success).
    """
    try:
        existing = await watcher.get_by_info_item_id(str(item.info_item_id))
    except WatcherResponseError:
        logger.exception(
            "Watcher conflict recovery lookup failed for InfoItem %s: response contract "
            "mismatch (watcher_client SDK may be stale)",
            item.info_item_id,
        )
        return WatcherSyncOutcome.CONTRACT_ERROR
    except Exception:
        logger.exception(
            "Watcher conflict recovery lookup failed for InfoItem %s", item.info_item_id
        )
        return WatcherSyncOutcome.FAILED
    if existing is None:
        logger.error(
            "Watcher reported a conflict for InfoItem %s but no linked WatchedItem was found",
            item.info_item_id,
        )
        return WatcherSyncOutcome.FAILED
    item.watcher_item_id = str(existing.id)
    await session.commit()
    logger.info(
        "Adopted existing WatchedItem %s for InfoItem %s after provisioning conflict",
        existing.id,
        item.info_item_id,
    )
    return WatcherSyncOutcome.OK


async def sync_on_source_swap(
    session: AsyncSession,
    watcher: WatcherClient | None,
    info_item: InfoItem,
    new_info_source: InfoSource,
) -> WatcherSyncOutcome:
    """Push updated URL, specs, and source ID to Watcher after a primary swap.

    No-op when the InfoItem has no ``watcher_item_id`` (pre-integration item or
    provisioning was never attempted). The "Begin watching" dashboard affordance
    handles on-demand provisioning in that case.

    Returns a :class:`WatcherSyncOutcome`: ``SKIPPED`` when no Watcher is
    configured or the item isn't watched, ``OK`` on success, ``FAILED`` when the
    call raised (logged and swallowed).
    """
    if watcher is None or not info_item.watcher_item_id:
        return WatcherSyncOutcome.SKIPPED
    try:
        await watcher.patch_watched_item(
            info_item.watcher_item_id,
            effective_url=new_info_source.url,
            source_specs=list(new_info_source.source_specs),
            archiver_info_source_id=str(new_info_source.info_source_id),
        )
        return WatcherSyncOutcome.OK
    except WatcherResponseError:
        logger.exception(
            "Watcher sync failed for InfoItem %s after primary source swap: response "
            "contract mismatch (watcher_client SDK may be stale)",
            info_item.info_item_id,
        )
        return WatcherSyncOutcome.CONTRACT_ERROR
    except Exception:
        logger.exception(
            "Watcher sync failed for InfoItem %s after primary source swap",
            info_item.info_item_id,
        )
        return WatcherSyncOutcome.FAILED


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
        except WatcherResponseError:
            logger.exception(
                "Watcher spec sync failed for InfoItem %s: response contract mismatch "
                "(watcher_client SDK may be stale)",
                item.info_item_id,
            )
        except Exception:
            logger.exception("Watcher spec sync failed for InfoItem %s", item.info_item_id)
