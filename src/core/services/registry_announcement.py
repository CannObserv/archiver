"""The ``info.registry`` announcement — one emitter behind every mutation site.

Archiver is the producer of the registry announcement channel (archiver#141):
per-InfoItem LWW state, deltas through the transactional outbox, snapshots
published directly on a timer. This module owns the *delta* half: the atomic
generation bump, the joined read of announced state, and the ``changes_outbox``
row, written inside the caller's transaction so a rolled-back mutation leaves
no orphaned announcement. Roughly sixteen mutation sites across the API and
dashboard call in here; hand-building the payload at each would drift.

**The live/revoked/skip rule.** An item with an active primary binding
announces live — provided the source carries non-empty ``source_specs``, which
co-core's live-entry validator requires. Otherwise it announces ``revoked`` *if
it was ever announced*
— skipping would leave a consumer fetching the old URL forever, which is the
drift bug this channel exists to remove; a later re-binding announces live at a
higher generation and the consumer resurrects the key (watcher#254 tests
exactly this). A never-announced sourceless item emits nothing: no consumer
knows the key, and co-core's validator would reject a live announcement without
``info_source_id``/``url``/``source_specs`` anyway.

**The generation bump is a single atomic UPDATE.** ``UPDATE … SET
announcement_generation = announcement_generation + 1 RETURNING`` — never
read-modify-write in Python: two concurrent mutations would both read N and
write N+1, and every consumer would discard the second announcement as a
duplicate (apply-iff-greater never fires). This is the failure the token
exists to prevent, reintroduced by the obvious implementation.

**The bump precedes the payload, so no announcement carries generation 0**
(archiver#161) — the floor on the wire is 1, and that is load-bearing rather
than incidental. The return leg spells "Watcher has never reconciled anything"
as ``applied_generation = 0``, so an announcement at 0 would make the wire value
ambiguous and the drift detector read an unapplied item as clean. Keep the bump
above the build; do not add a path that emits a generation it read rather than
incremented. ``0`` in the *column* still means never announced.

**Deletion** (``announce_info_item_revoked``) additionally records a
``RevokedInfoItem`` row, because the item row is about to be gone and the
snapshot's full-set republish must keep tombstoning the key — absence from a
snapshot is deliberately *not* the delete signal.
"""

from datetime import UTC, datetime

from co_core.pure.adapters.bus.streams import INFO_REGISTRY
from co_core.pure.models.changes import RegistryAnnouncementEmit
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.core.models import (
    ChangesOutboxRow,
    InfoItem,
    InfoItemSource,
    InfoSource,
    RevokedInfoItem,
)

INFO_REGISTRY_TOPIC = INFO_REGISTRY


def build_live_announcement(
    *, item: InfoItem, source: InfoSource, generation: int
) -> RegistryAnnouncementEmit:
    """One payload shape for both emit paths — delta (here) and snapshot.

    Two builders would drift, and the failure directions differ: a delta that
    diverges dead-letters loudly in the outbox build phase, but the snapshot
    publishes directly, so its divergence would reach the stream.
    """
    return RegistryAnnouncementEmit(
        occurred_at=datetime.now(UTC),
        info_item_id=str(item.info_item_id),
        generation=generation,
        info_source_id=str(source.info_source_id),
        url=source.url,
        source_specs=source.source_specs,
        active=item.watch_active,
        watch_spec=item.watch_spec,
    )


def build_tombstone(*, info_item_id: ULID | str, generation: int) -> RegistryAnnouncementEmit:
    """Minimal by contract: identity + generation + revoked, nothing hydrated."""
    return RegistryAnnouncementEmit(
        occurred_at=datetime.now(UTC),
        info_item_id=str(info_item_id),
        generation=generation,
        revoked=True,
    )


async def _bump_generation(session: AsyncSession, info_item_id: ULID) -> int | None:
    """Atomically increment and return the item's generation; None if no row.

    ``announced_at`` rides the same UPDATE (archiver#151): it is the drift
    detector's clock — "applied lags announced by 40m" needs to know when the
    announced generation went out, and ``changes_outbox.published_at`` is
    pruned on a retention window (archiver#189), so the stamp lives on the item.
    """
    return (
        await session.execute(
            update(InfoItem)
            .where(InfoItem.info_item_id == info_item_id)
            .values(
                announcement_generation=InfoItem.announcement_generation + 1,
                announced_at=datetime.now(UTC),
            )
            .returning(InfoItem.announcement_generation)
        )
    ).scalar_one_or_none()


async def _active_source(session: AsyncSession, info_item_id: ULID) -> InfoSource | None:
    return (
        await session.execute(
            select(InfoSource)
            .join(InfoItemSource, InfoItemSource.info_source_id == InfoSource.info_source_id)
            .where(
                InfoItemSource.info_item_id == info_item_id,
                InfoItemSource.deactivated_at.is_(None),
            )
        )
    ).scalar_one_or_none()


def _add_outbox_row(session: AsyncSession, event: RegistryAnnouncementEmit) -> None:
    session.add(ChangesOutboxRow(topic=INFO_REGISTRY_TOPIC, payload=event.model_dump(mode="json")))


async def announce_info_item(session: AsyncSession, info_item_id: ULID) -> None:
    """Emit the item's current announced state as a delta, bumping generation.

    Call once per mutation flow, after every write and before the commit — a
    flow that mutates twice (a swap: deactivate + bind) announces **once**,
    with the final state. Two calls in one flow would emit revoked-then-live
    and the consumer would destroy and recreate its row, losing local state.

    Silent no-op when the item does not exist (deletion has its own path) and
    when a sourceless item has never been announced.
    """
    generation = await _bump_generation(session, info_item_id)
    if generation is None:
        return

    item = (
        await session.execute(select(InfoItem).where(InfoItem.info_item_id == info_item_id))
    ).scalar_one()
    source = await _active_source(session, info_item_id)

    # Announceable-as-live needs non-empty source_specs too: co-core's validator
    # refuses a live announcement with an empty list ("nothing to reconcile
    # against"), so an item bound to a spec-less source follows the same rule as
    # an unbound one. The spec edit that later fills the list fans out through
    # announce_for_info_source and resurrects the key at a higher generation.
    if source is None or not source.source_specs:
        if generation == 1:
            # Never announced: no consumer knows the key. The bump is kept —
            # harmless, and un-bumping would need a second UPDATE racing the
            # first — so the first real announcement goes out as gen 2.
            return
        event = build_tombstone(info_item_id=info_item_id, generation=generation)
    else:
        event = build_live_announcement(item=item, source=source, generation=generation)
    _add_outbox_row(session, event)


async def announce_for_info_source(session: AsyncSession, info_source_id: ULID) -> int:
    """Fan out one InfoSource mutation to every item it actively backs.

    ``info_item_sources`` has no uniqueness on ``info_source_id`` — one source
    can be the active primary for several items, and the announcement grain is
    the item. Each gets its own generation bump. Returns the announcement
    count (zero for a source nothing is bound to — a fresh create).

    Known scale ceiling (CR round 3, #14): this is N sequential
    announce_info_item calls — an UPDATE plus two SELECTs each — inside one
    transaction, holding N row locks. Nothing at O(10) items; a spec edit on a
    source backing O(10^3) becomes ~3k round-trips. The batch rewrite (one
    UPDATE ... RETURNING over the id set, one joined SELECT) belongs here when
    the corpus gets there.
    """
    item_ids = (
        (
            await session.execute(
                select(InfoItemSource.info_item_id).where(
                    InfoItemSource.info_source_id == info_source_id,
                    InfoItemSource.deactivated_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    for item_id in item_ids:
        await announce_info_item(session, item_id)
    return len(item_ids)


async def announce_info_item_revoked(session: AsyncSession, item: InfoItem) -> None:
    """Emit the deletion tombstone and record it for snapshot republish.

    Call **before** ``session.delete(item)``, in the deletion's transaction:
    the bump needs the row, and the ``RevokedInfoItem`` record is what the
    hourly full set reads once the row is gone. Unlike unbinding, deletion
    tombstones even a never-announced item — the row is about to not exist, so
    no later mutation can ever speak for this key again.
    """
    generation = await _bump_generation(session, item.info_item_id)
    if generation is None:
        return
    session.add(RevokedInfoItem(info_item_id=item.info_item_id, generation=generation))
    _add_outbox_row(session, build_tombstone(info_item_id=item.info_item_id, generation=generation))
