"""Periodic full-set republish of ``info.registry`` (archiver#141).

Deltas ride the transactional outbox; this task republishes the **entire key
set** directly, on a timer, so a consumer converges regardless of stream
trimming — cold start, replay after an outage, or a key whose delta was
dead-lettered. It deliberately bypasses the outbox: a full republish every
period would put a whole key set through the drain on a timer, churning the
table and the live partial index for events that carry no transactional
obligation - the snapshot is an idempotent LWW read of current state, not a
delta bound to a mutation's commit.

Note the reason this is *not*: unbounded growth. ``changes_outbox`` now has a
retention pass (``outbox_prune.py``, archiver#189), so the row count is bounded
either way. That removes one argument for bypassing the outbox and none of the
others - a snapshot still has nothing to be transactional about, and routing it
through the outbox would still be churn for churn's sake.

**Durability, stated because the deploy table carries the column:** this path
has **no retry**. The outbox drain retries a delta indefinitely; a snapshot
entry lost to a broker outage is corrected by the next period, not by a
re-attempt. A failed entry is logged and the set continues — absence from a
full set is deliberately not a signal, so a partial set costs nothing.

**Generations are read, never bumped.** A bump per republish would make every
snapshot look like a mutation, race concurrent deltas for the counter, and
defeat the consumer's apply-iff-greater guard. A healthy consumer sees the
same generation it already holds and ignores the entry — the snapshot only
does work for a consumer that is behind.

Reading rather than bumping is also why *this* path was the only one that could
put generation 0 on the wire (archiver#161): the delta path bumps before it
builds a payload, so its floor is 1, but a snapshot faithfully republishes a row
that never passed an announce site. Migration ``e3a71c40b9d2`` removed that
population. A live entry at 0 is now logged as an anomaly rather than silently
republished — post-backfill it means an announceable item mutated without
announcing, i.e. a missing call site. It is still **published**: skipping would
drop a real item from the registry, and bumping here would break the rule above.

**Retention rides these publishes** (``BusPublish.maxlen``): a config/state
stream's cap is a consumer contract, because consumers boot by replaying from
``0-0`` — the floor is "at least one full set plus the deltas since". The
operator-side ``XTRIM`` loop in ``publisher.run`` explicitly excludes this
topic; sizing it from the fact stream's knob would silently break that floor.
Since archiver#373 item 4 the cap is ``content.fetch-policy``'s rule:
``max(resolved, RETAINED_FULL_SETS × full set)``, tombstones counted, computed
only by a complete set. ``run`` hands each set's cap to the outbox drain through
``topic_maxlen``, so deltas carry the last set's cap and none before the first.

The full set is: every announceable item (active binding, non-empty
``source_specs``) live; every previously-announced but currently
unannounceable item revoked; every deleted item (``revoked_info_items``)
revoked. Never-announced keys are absent — no consumer knows them. The
announceability rule is shared with the delta path via the builders in
``src.core.services.registry_announcement``, so the two paths cannot drift.
So is the host rule (archiver#360): each live row carries its source's
``Domain`` from the same query, handed to the same builder, which judges
suspension and resolves the cadence's domain tier from it (archiver#364).
Each live row carries the item's ``TemporalProfile`` too (archiver#365), whose
*stored* result is the cadence's top tier: the snapshot never reads the clock,
so it replays the interval the last delta announced, at that delta's generation.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import MutableMapping
from dataclasses import dataclass

from co_core.effects.bus import BusPublish
from co_core.pure.adapters.bus.envelope import to_wire
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.logging import get_logger
from src.core.models import (
    Domain,
    InfoItem,
    InfoItemSource,
    InfoSource,
    RevokedInfoItem,
    TemporalProfile,
)
from src.core.services.registry_announcement import (
    INFO_REGISTRY_TOPIC,
    build_live_announcement,
    build_tombstone,
    source_is_announceable,
)

logger = get_logger(__name__)

DEFAULT_SNAPSHOT_INTERVAL_SECONDS = 3600
"""One hour (the design's ratified period). Not the convergence guarantee for a
healthy delta — that is outbox latency, sub-second — it bounds the failure
cases: a trimmed stream, a dead-lettered delta, a cold-starting consumer."""

DEFAULT_REGISTRY_STREAM_MAXLEN = 1_000
"""The cap's default; the full-set floor raises it, never lowers it (archiver#373).

**Sized against the set, not the broker's comfort** (the watcher#292 lesson,
``content.fetch-policy``'s ``DEFAULT_FETCH_POLICY_STREAM_MAXLEN``): Watcher
replays this stream groupless from ``0-0`` at every boot, so every retained
entry is read at every boot. At 2026-11-09's 21-entry set the stream gains about
500 entries a day (an hourly set, one per deploy, the deltas), so 50,000 meant
about 100 days of replay; 1,000 is about two days, still far above the "one full
set plus the deltas since" floor a ``0-0`` consumer needs.

**Mirrored on the broker node** (archiver#196, CannObserv/broker#139):
``src/broker/bus_health.py`` carries this number as
``REGISTRY_PRODUCER_MAXLEN``, ``RETAINED_FULL_SETS`` below as
``REGISTRY_RETAINED_FULL_SETS`` and ``DEFAULT_SNAPSHOT_INTERVAL_SECONDS`` as
``REGISTRY_REPUBLISH_PERIOD_SECONDS``, combined in ``REGISTRY_FULL_SET_FLOOR``.
Its tests cite these three names in this module: rename none of them without a
matching broker commit. Index: that repo's ``docs/BUS-HEALTH.md``, "Mirrored
constants", and ``docs/LWW-CAP.md``.

**What the mirror feeds** (broker ``38401ba``): the stream-too-long ceiling is
``max(1,000, 10 × the set read off the stream)`` plus 10%, and the shrink
check (``entries-removed``, CannObserv/broker#42) is scoped by this default, never
by the floored cap. ``MAXLEN ~`` never leaves fewer than the cap in force, which
is never under 1,000, so a removal that leaves fewer is a fault whatever the set.
Broker's set reading counts deltas and each deploy's set, so it reads high, the
safe side. **Lowered here** unmirrored, ``entries-removed`` fires at each trim.
**Raised past the 10% margin**, the ceiling fires early.

The mirror's real hazard is ``ARCHIVER_REGISTRY_STREAM_MAXLEN`` (``MAXLEN_ENV``):
it moves the cap in force with no commit in either repo. Under the floor it can
no longer drop the cap below ``RETAINED_FULL_SETS`` sets, but it can still raise
it past broker's ceiling or lower it under this default, so setting it still
obliges a note to broker (``docs/ENVIRONMENT_BUS.md``)."""

RETAINED_FULL_SETS = 10
"""The floor's multiplier: the cap never drops below ten complete sets, so a
set larger than the default cannot trim its own earlier entries. Broker's
``REGISTRY_RETAINED_FULL_SETS``. The same value as
``fetch_policy_snapshot.RETAINED_FULL_SETS``, deliberately not the same
constant: either stream's owner moves its number alone."""

MAXLEN_ENV = "ARCHIVER_REGISTRY_STREAM_MAXLEN"


def resolve_snapshot_interval(raw: str | None) -> float:
    """Parse ARCHIVER_REGISTRY_SNAPSHOT_INTERVAL (seconds) defensively."""
    if raw is None or not raw.strip():
        return DEFAULT_SNAPSHOT_INTERVAL_SECONDS
    try:
        value = float(raw)
    except ValueError:
        logger.warning(
            "Invalid ARCHIVER_REGISTRY_SNAPSHOT_INTERVAL; falling back to default",
            extra={"value": raw, "default": DEFAULT_SNAPSHOT_INTERVAL_SECONDS},
        )
        return DEFAULT_SNAPSHOT_INTERVAL_SECONDS
    return value if value > 0 else DEFAULT_SNAPSHOT_INTERVAL_SECONDS


def resolve_registry_maxlen(raw: str | None, *, floor: int = 1) -> int:
    """Parse ``ARCHIVER_REGISTRY_STREAM_MAXLEN`` defensively; never under ``floor``.

    ``resolve_fetch_policy_maxlen``'s rule: an invalid or non-positive value
    falls back to the default with a warning, and the floor wins over both. An
    explicit value under the floor is the one misconfiguration the floor
    overrides, so it is reported.
    """
    bounded = max(DEFAULT_REGISTRY_STREAM_MAXLEN, floor)
    if raw is None or not raw.strip():
        return bounded
    try:
        value = int(raw)
    except ValueError:
        logger.warning(
            "Invalid %s; falling back to default",
            MAXLEN_ENV,
            extra={"value": raw, "floor": floor, "effective": bounded},
        )
        return bounded
    if value <= 0:
        logger.warning(
            "Non-positive %s; falling back to default",
            MAXLEN_ENV,
            extra={"value": raw, "floor": floor, "effective": bounded},
        )
        return bounded
    if floor > value:
        logger.warning(
            "%s is below the full-set floor; using the floor",
            MAXLEN_ENV,
            extra={"value": raw, "floor": floor, "effective": floor},
        )
    return max(value, floor)


@dataclass(frozen=True)
class RegistrySetResult:
    """What one full set did: entries published by kind, and the cap they carried."""

    live: int
    revoked: int
    maxlen: int


async def _collect_full_set(session: AsyncSession) -> tuple[list, list]:
    """Return (live [(item, source, domain, profile)], revoked [(info_item_id, generation)])."""
    bound = (
        await session.execute(
            select(InfoItem, InfoSource, Domain, TemporalProfile)
            .join(InfoItemSource, InfoItemSource.info_item_id == InfoItem.info_item_id)
            .join(InfoSource, InfoSource.info_source_id == InfoItemSource.info_source_id)
            .outerjoin(Domain, Domain.name == InfoSource.domain_name)
            .outerjoin(TemporalProfile, TemporalProfile.info_item_id == InfoItem.info_item_id)
            .where(InfoItemSource.deactivated_at.is_(None))
        )
    ).all()
    live = [
        (item, source, domain, profile)
        for item, source, domain, profile in bound
        if source_is_announceable(source)
    ]
    # Bound to a spec-less source: unannounceable-as-live, same rule as the
    # delta path — revoked if ever announced.
    specless = [
        (item.info_item_id, item.announcement_generation)
        for item, source, _domain, _profile in bound
        if not source_is_announceable(source) and item.announcement_generation > 0
    ]

    # NOT EXISTS rather than a materialized notin_ list (CR round 3, #15):
    # the IN-list would grow with the corpus, and the empty-set special case
    # it required read as load-bearing.
    active_binding = (
        select(InfoItemSource.info_item_id)
        .where(
            InfoItemSource.info_item_id == InfoItem.info_item_id,
            InfoItemSource.deactivated_at.is_(None),
        )
        .exists()
    )
    unbound = (
        await session.execute(
            select(InfoItem.info_item_id, InfoItem.announcement_generation).where(
                InfoItem.announcement_generation > 0,
                ~active_binding,
            )
        )
    ).all()

    deleted = (
        await session.execute(select(RevokedInfoItem.info_item_id, RevokedInfoItem.generation))
    ).all()

    revoked = [(str(i), g) for i, g in [*specless, *unbound, *deleted]]
    return live, revoked


async def publish_full_set(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    publisher,
) -> RegistrySetResult:
    """Publish one full set directly to ``info.registry``, with its floored cap.

    The cap is ``max(resolved, RETAINED_FULL_SETS × entries built)``: the floor
    counts the set as collected, tombstones included, never the entries that
    landed, so a failed publish cannot shrink it. This function collects the
    whole set itself, so the floor is never computed from a partial batch.

    Per-entry failures are logged and skipped — no retry (the next period is
    the repair), no abort (a partial set costs nothing, since absence is not a
    signal and every entry is idempotent under apply-iff-greater).
    """
    async with session_factory() as session:
        live, revoked = await _collect_full_set(session)
        for item, _source, _domain, _profile in live:
            if item.announcement_generation <= 0:
                logger.warning(
                    "Announceable item republished at generation 0 — a mutation "
                    "reached announceable state without announcing (archiver#161)",
                    extra={"info_item_id": str(item.info_item_id)},
                )
        events = [
            build_live_announcement(
                item=item,
                source=source,
                generation=item.announcement_generation,
                domain=domain,
                profile=profile,
            )
            for item, source, domain, profile in live
        ] + [
            build_tombstone(info_item_id=info_item_id, generation=generation)
            for info_item_id, generation in revoked
        ]

    maxlen = resolve_registry_maxlen(
        os.environ.get(MAXLEN_ENV), floor=len(events) * RETAINED_FULL_SETS
    )
    published_live = published_revoked = 0
    for event in events:
        try:
            fields = to_wire(event)
            await publisher.execute(
                BusPublish(topic=INFO_REGISTRY_TOPIC, fields=fields, maxlen=maxlen)
            )
        except Exception:
            logger.warning(
                "Snapshot entry failed to publish; the next period is the repair",
                extra={"info_item_id": event.info_item_id, "generation": event.generation},
                exc_info=True,
            )
            continue
        if event.revoked:
            published_revoked += 1
        else:
            published_live += 1
    return RegistrySetResult(live=published_live, revoked=published_revoked, maxlen=maxlen)


async def run(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    publisher,
    interval: float,
    topic_maxlen: MutableMapping[str, int],
    stop_event: asyncio.Event,
    trigger: asyncio.Event | None = None,
) -> None:
    """Publish a full set at startup, then every ``interval`` seconds.

    After each set, ``topic_maxlen[INFO_REGISTRY_TOPIC]`` takes its cap: the
    outbox drain reads that mapping per row, so deltas carry the last complete
    set's floor, and none before the first set (archiver#373 item 4).

    The startup set means a service restart converges consumers without
    waiting a period. ``trigger`` is the operator's "republish now" — set it
    (the tools route does) and the loop publishes immediately, then resumes
    its cadence. A cycle that raises is logged and the loop continues: the
    next period is the repair mechanism, so the loop dying IS the failure.
    """
    trigger = trigger or asyncio.Event()
    while not stop_event.is_set():
        try:
            result = await publish_full_set(session_factory=session_factory, publisher=publisher)
            topic_maxlen[INFO_REGISTRY_TOPIC] = result.maxlen
            logger.info(
                "Registry snapshot published",
                extra={
                    "live": result.live,
                    "revoked": result.revoked,
                    "maxlen": result.maxlen,
                    "interval_seconds": interval,
                },
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Registry snapshot cycle failed; next period is the repair")

        stop_wait = asyncio.create_task(stop_event.wait())
        trigger_wait = asyncio.create_task(trigger.wait())
        done, pending = await asyncio.wait(
            {stop_wait, trigger_wait}, timeout=interval, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
        if trigger_wait in done:
            trigger.clear()
