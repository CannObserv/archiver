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
co-core's live-entry validator requires (``source_is_announceable``, with its
SQL twin ``announceable_specs_clause`` for the panel - one rule, archiver#167).
Otherwise it announces ``revoked`` *if it was ever announced*
— skipping would leave a consumer fetching the old URL forever, which is the
drift bug this channel exists to remove; a later re-binding announces live at a
higher generation and the consumer resurrects the key (watcher#254 tests
exactly this). A never-announced sourceless item emits nothing: no consumer
knows the key, and co-core's validator would reject a live announcement without
``info_source_id``/``url``/``source_specs`` anyway - and its generation stays
at 0, so ``> 0`` means "was announced" to the snapshot as well (archiver#167).

**Policy writes announce through ``announce_policy_change``.** Pause and cadence
cannot change announceability, so on an unannounceable item they leave the
key's announced state exactly where it was: nothing to emit, no generation to
burn. Re-tombstoning a revoked key on every stale-tab click is pure wire churn,
and on a key no consumer ever held it is a tombstone the full set would then
republish every period (archiver#167). It is *not* visible drift: the panel
renders ``not_watching`` for an unannounceable item, which carries none.

**The binding path skips an already-revoked key too** (archiver#293). A binding
or spec mutation *can* change announceability, so it cannot skip on the kind of
write; it skips on the kind of the last announcement instead.
``info_items.announced_revoked``, written in the same UPDATE as the bump, tells
"was live, now isn't" (a tombstone is owed) from "was already revoked" (nothing
changed). The snapshot keeps republishing the tombstone either way.

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

from collections.abc import Sequence
from datetime import UTC, datetime

from co_core.pure.adapters.bus.streams import INFO_REGISTRY
from co_core.pure.models.changes import RegistryAnnouncementEmit
from sqlalchemy import ColumnElement, func, select, update
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


async def _bump_generations(
    session: AsyncSession, *, live: Sequence[ULID], tombstoned: Sequence[ULID]
) -> dict[ULID, int]:
    """Atomically increment each item's generation; returns the new one per id.

    One ``UPDATE … RETURNING`` over the whole set; ids with no row are simply
    absent from the result. ``announced_at`` rides the same statement
    (archiver#151): it is the drift detector's clock — "applied lags announced
    by 40m" needs to know when the announced generation went out, and
    ``changes_outbox.published_at`` is pruned on a retention window
    (archiver#189), so the stamp lives on the item. ``announced_revoked`` rides
    it too (archiver#293), set per row from which list the id is in, so the kind
    it records is always the kind of the generation beside it.
    """
    return dict(
        (
            await session.execute(
                update(InfoItem)
                .where(InfoItem.info_item_id.in_([*live, *tombstoned]))
                .values(
                    announcement_generation=InfoItem.announcement_generation + 1,
                    announced_at=datetime.now(UTC),
                    announced_revoked=InfoItem.info_item_id.in_(tombstoned),
                )
                .returning(InfoItem.info_item_id, InfoItem.announcement_generation)
            )
        )
        .tuples()
        .all()
    )


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


def source_is_announceable(source: InfoSource | None) -> bool:
    """Whether ``source`` can back a *live* announcement: non-empty spec list.

    co-core's validator refuses a live entry with empty ``source_specs``
    ("nothing to reconcile against"). A non-list is refused too, matching the
    SQL form - unreachable through the app, whose write paths validate a list,
    but a hand-edited row must land on the same side of both.
    """
    if source is None:
        return False
    specs = source.source_specs
    return isinstance(specs, list) and len(specs) > 0


def announceable_specs_clause() -> ColumnElement[bool]:
    """``source_is_announceable`` as SQL over ``InfoSource.source_specs``.

    ``jsonb_typeof`` guards the length call: ``jsonb_array_length`` *errors* on
    a non-array, and the panel aggregates this on a render path archiver#151
    made unfailable. ``coalesce`` pins NULL to false so the two forms agree
    value-for-value, not just on truthiness. Kept beside the Python form so a
    change to one is a diff against the other; a parity test holds them.
    """
    return func.coalesce(
        (func.jsonb_typeof(InfoSource.source_specs) == "array")
        & (func.jsonb_array_length(InfoSource.source_specs) > 0),
        False,
    )


async def is_announceable(session: AsyncSession, info_item_id: ULID) -> bool:
    """Whether the item would announce *live* right now."""
    return source_is_announceable(await _active_source(session, info_item_id))


def _add_outbox_row(session: AsyncSession, event: RegistryAnnouncementEmit) -> None:
    session.add(ChangesOutboxRow(topic=INFO_REGISTRY_TOPIC, payload=event.model_dump(mode="json")))


async def announce_info_item(session: AsyncSession, info_item_id: ULID) -> None:
    """Emit the item's current announced state as a delta, bumping generation.

    Call once per mutation flow, after every write and before the commit — a
    flow that mutates twice (a swap: deactivate + bind) announces **once**,
    with the final state. Two calls in one flow would emit revoked-then-live
    and the consumer would destroy and recreate its row, losing local state.

    Silent no-op when the item does not exist (deletion has its own path),
    when an unannounceable item has never been announced — without a bump, so
    its generation stays 0 — and when it is already revoked (archiver#293).
    """
    await _announce_many(session, [info_item_id], revoke=True)


async def announce_policy_change(session: AsyncSession, info_item_id: ULID) -> bool:
    """Announce a pause or cadence write; returns whether anything was emitted.

    Live when the item is announceable, otherwise nothing — no tombstone, no
    bump. A policy write never changes announceability, so an unannounceable
    item's key stays where it was (revoked, or unknown to every consumer), and
    the next binding announces live with the policy written meanwhile.
    """
    return await _announce_many(session, [info_item_id], revoke=False) > 0


async def _announce_many(session: AsyncSession, item_ids: Sequence[ULID], *, revoke: bool) -> int:
    """Announce each item's current state; returns how many announcements went out.

    The one emit path, for a single item and a fan-out alike, in a fixed number
    of statements however many items: lock, read the active sources, bump, and
    hydrate the live items (CR round 3, #14). Missing ids are skipped silently.

    The lock comes first, so a concurrent binding or policy write serializes
    behind it and the state read is the state announced. It is taken in id
    order: two fan-outs over overlapping item sets acquire their row locks in
    the same sequence, so neither can hold one the other is waiting on.
    """
    if not item_ids:
        return 0
    locked = (
        await session.execute(
            select(
                InfoItem.info_item_id,
                InfoItem.announcement_generation,
                InfoItem.announced_revoked,
            )
            .where(InfoItem.info_item_id.in_(item_ids))
            .order_by(InfoItem.info_item_id)
            .with_for_update()
        )
    ).all()
    if not locked:
        return 0
    sources = dict(
        (
            await session.execute(
                select(InfoItemSource.info_item_id, InfoSource)
                .join(InfoSource, InfoSource.info_source_id == InfoItemSource.info_source_id)
                .where(
                    InfoItemSource.info_item_id.in_([row[0] for row in locked]),
                    InfoItemSource.deactivated_at.is_(None),
                )
            )
        )
        .tuples()
        .all()
    )

    live: list[ULID] = []
    tombstoned: list[ULID] = []
    for info_item_id, current, already_revoked in locked:
        if source_is_announceable(sources.get(info_item_id)):
            live.append(info_item_id)
        # Unannounceable and never announced (no consumer knows the key), a
        # policy write (the key's announced state cannot have changed), or
        # already tombstoned (archiver#293): nothing to say, no generation to
        # burn. Otherwise the key was live and a tombstone is owed.
        elif current > 0 and revoke and not already_revoked:
            tombstoned.append(info_item_id)
    if not live and not tombstoned:
        return 0

    generations = await _bump_generations(session, live=live, tombstoned=tombstoned)
    items = (
        {
            item.info_item_id: item
            for item in (
                await session.execute(select(InfoItem).where(InfoItem.info_item_id.in_(live)))
            ).scalars()
        }
        if live
        else {}
    )
    for info_item_id, _current, _revoked in locked:
        if info_item_id in items:
            event = build_live_announcement(
                item=items[info_item_id],
                source=sources[info_item_id],
                generation=generations[info_item_id],
            )
        elif info_item_id in generations:
            event = build_tombstone(info_item_id=info_item_id, generation=generations[info_item_id])
        else:
            continue
        _add_outbox_row(session, event)
    return len(generations)


async def announce_for_info_source(session: AsyncSession, info_source_id: ULID) -> int:
    """Fan out one InfoSource mutation to every item it actively backs.

    ``info_item_sources`` has no uniqueness on ``info_source_id`` — one source
    can be the active primary for several items, and the announcement grain is
    the item. Each gets its own generation bump. Returns the number of
    announcements emitted — zero for a source nothing is bound to (a fresh
    create), and skipped items (never announced, already revoked) don't count.

    One batch over the id set, not N ``announce_info_item`` calls (CR round 3,
    #14): the statement count is fixed, so a spec edit on a source backing
    O(10^3) items is five round-trips, not ~4k. It still holds N row locks for
    the transaction - inherent, since every item's generation moves.
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
    return await _announce_many(session, item_ids, revoke=True)


async def announce_info_item_revoked(session: AsyncSession, item: InfoItem) -> None:
    """Emit the deletion tombstone and record it for snapshot republish.

    Call **before** ``session.delete(item)``, in the deletion's transaction:
    the bump needs the row, and the ``RevokedInfoItem`` record is what the
    hourly full set reads once the row is gone. Unlike unbinding, deletion
    tombstones even a never-announced item — the row is about to not exist, so
    no later mutation can ever speak for this key again.
    """
    generation = (await _bump_generations(session, live=[], tombstoned=[item.info_item_id])).get(
        item.info_item_id
    )
    if generation is None:
        return
    session.add(RevokedInfoItem(info_item_id=item.info_item_id, generation=generation))
    _add_outbox_row(session, build_tombstone(info_item_id=item.info_item_id, generation=generation))
