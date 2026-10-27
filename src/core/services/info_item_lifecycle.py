"""Watch lifecycle: archive and restore an InfoItem (archiver#361).

Archive is operator intent (design D5), so it lives here, not in Watcher. It is
**orthogonal to pause** (D1), the ``domains.archived_at`` pattern: archive sets
``info_items.archived_at`` and leaves ``watch_active`` alone. The announcement
resolves ``active=false`` while archived (``resolved_active``), and restore
returns the item to its own state - a paused item stays paused, an active one
resumes. Watcher forgets the pause on restore; this deliberately does not.

**Watch-only** (D4): authoring, bindings, rep specs, replication and persist
issuance ignore the column. Permanent delete stays the ``revoked`` tombstone
(``DELETE /info-items/{id}``), with no archive required first.

**A call that changes nothing writes and announces nothing.** Archive keeps the
first timestamp. A real transition announces once through
``announce_policy_change``, so every restore outranks the archive before it -
Watcher's reconcile re-arms an item only on a higher generation (watcher#254
CR-23). An unannounceable item stores the state and emits nothing (#167); its
next binding announces with the archive in place.

**Lock order: the item, then its host's Domain row** - the order every
announce takes. The item is locked ``FOR UPDATE`` before the read that decides
whether anything changes, so two archives serialize and the second sees the
first. A caller already holding the item lock (#365's boundary job) can call in:
re-locking a row the transaction holds does not wait. The caller commits.
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.core.models import InfoItem
from src.core.services.registry_announcement import announce_policy_change


async def _locked(session: AsyncSession, info_item_id: ULID) -> InfoItem | None:
    return (
        await session.execute(
            select(InfoItem)
            .where(InfoItem.info_item_id == info_item_id)
            .with_for_update()
            # The session may hold a stale copy; the lock's read must win.
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


async def _set_archived_at(
    session: AsyncSession, info_item_id: ULID, *, archive: bool
) -> InfoItem | None:
    item = await _locked(session, info_item_id)
    if item is None or (item.archived_at is not None) == archive:
        return item
    item.archived_at = datetime.now(UTC) if archive else None
    await session.flush()
    await announce_policy_change(session, info_item_id)
    return item


async def archive_info_item(session: AsyncSession, info_item_id: ULID) -> InfoItem | None:
    """Archive the item's watch; returns the item, or ``None`` when it is missing.

    Idempotent: an archived item keeps its first ``archived_at`` and announces
    nothing.
    """
    return await _set_archived_at(session, info_item_id, archive=True)


async def restore_info_item(session: AsyncSession, info_item_id: ULID) -> InfoItem | None:
    """Clear the item's archive; returns the item, or ``None`` when it is missing.

    The item announces its own ``watch_active`` again (unless its host is
    suspended). Restoring an item that is not archived does nothing.
    """
    return await _set_archived_at(session, info_item_id, archive=False)
