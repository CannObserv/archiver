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

The full set is: every announceable item (active binding, non-empty
``source_specs``) live; every previously-announced but currently
unannounceable item revoked; every deleted item (``revoked_info_items``)
revoked. Never-announced keys are absent — no consumer knows them. The
announceability rule is shared with the delta path via the builders in
``src.core.services.registry_announcement``, so the two paths cannot drift.
"""

from __future__ import annotations

import asyncio

from co_core.effects.bus import BusPublish
from co_core.pure.adapters.bus.envelope import to_wire
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.logging import get_logger
from src.core.models import InfoItem, InfoItemSource, InfoSource, RevokedInfoItem
from src.core.services.registry_announcement import (
    INFO_REGISTRY_TOPIC,
    build_live_announcement,
    build_tombstone,
)

logger = get_logger(__name__)

DEFAULT_SNAPSHOT_INTERVAL_SECONDS = 3600
"""One hour (the design's ratified period). Not the convergence guarantee for a
healthy delta — that is outbox latency, sub-second — it bounds the failure
cases: a trimmed stream, a dead-lettered delta, a cold-starting consumer."""

DEFAULT_REGISTRY_STREAM_MAXLEN = 50_000
"""Approximate cap carried on every info.registry publish.

Derived from key count x sets retained, never from the fact stream's number:
at O(10^3) items on the 1-hour period that is ~24k entries/day, so 50k covers
roughly two days of full sets plus deltas — comfortably above the "one full
set plus the deltas since" floor a replay-from-0-0 consumer needs. Today's
corpus is O(10), making the default effectively unbounded; revisit the knob
(ARCHIVER_REGISTRY_STREAM_MAXLEN) as the corpus grows."""


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


def resolve_registry_maxlen(raw: str | None) -> int:
    """Parse ARCHIVER_REGISTRY_STREAM_MAXLEN defensively; never unbounded."""
    if raw is None or not raw.strip():
        return DEFAULT_REGISTRY_STREAM_MAXLEN
    try:
        value = int(raw)
    except ValueError:
        logger.warning(
            "Invalid ARCHIVER_REGISTRY_STREAM_MAXLEN; falling back to default",
            extra={"value": raw, "default": DEFAULT_REGISTRY_STREAM_MAXLEN},
        )
        return DEFAULT_REGISTRY_STREAM_MAXLEN
    return value if value > 0 else DEFAULT_REGISTRY_STREAM_MAXLEN


async def _collect_full_set(session: AsyncSession) -> tuple[list, list]:
    """Return (live [(item, source)], revoked [(info_item_id, generation)])."""
    bound = (
        await session.execute(
            select(InfoItem, InfoSource)
            .join(InfoItemSource, InfoItemSource.info_item_id == InfoItem.info_item_id)
            .join(InfoSource, InfoSource.info_source_id == InfoItemSource.info_source_id)
            .where(InfoItemSource.deactivated_at.is_(None))
        )
    ).all()
    live = [(item, source) for item, source in bound if source.source_specs]
    # Bound to a spec-less source: unannounceable-as-live, same rule as the
    # delta path — revoked if ever announced.
    specless = [
        (item.info_item_id, item.announcement_generation)
        for item, source in bound
        if not source.source_specs and item.announcement_generation > 0
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
    maxlen: int,
) -> tuple[int, int]:
    """Publish one full set directly to ``info.registry``; returns (live, revoked).

    Per-entry failures are logged and skipped — no retry (the next period is
    the repair), no abort (a partial set costs nothing, since absence is not a
    signal and every entry is idempotent under apply-iff-greater).
    """
    async with session_factory() as session:
        live, revoked = await _collect_full_set(session)
        for item, _source in live:
            if item.announcement_generation <= 0:
                logger.warning(
                    "Announceable item republished at generation 0 — a mutation "
                    "reached announceable state without announcing (archiver#161)",
                    extra={"info_item_id": str(item.info_item_id)},
                )
        events = [
            build_live_announcement(
                item=item, source=source, generation=item.announcement_generation
            )
            for item, source in live
        ] + [
            build_tombstone(info_item_id=info_item_id, generation=generation)
            for info_item_id, generation in revoked
        ]

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
    return published_live, published_revoked


async def run(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    publisher,
    interval: float,
    maxlen: int,
    stop_event: asyncio.Event,
    trigger: asyncio.Event | None = None,
) -> None:
    """Publish a full set at startup, then every ``interval`` seconds.

    The startup set means a service restart converges consumers without
    waiting a period. ``trigger`` is the operator's "republish now" — set it
    (the tools route does) and the loop publishes immediately, then resumes
    its cadence. A cycle that raises is logged and the loop continues: the
    next period is the repair mechanism, so the loop dying IS the failure.
    """
    trigger = trigger or asyncio.Event()
    while not stop_event.is_set():
        try:
            live, revoked = await publish_full_set(
                session_factory=session_factory, publisher=publisher, maxlen=maxlen
            )
            logger.info(
                "Registry snapshot published",
                extra={"live": live, "revoked": revoked, "interval_seconds": interval},
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
