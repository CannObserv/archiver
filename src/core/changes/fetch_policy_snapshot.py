"""Periodic full-set republish of ``content.fetch-policy`` (archiver#366).

Port of Watcher's producer (watcher ``src/core/fetch_policy.py``,
``src/workers/fetch_policy.py``), in ``info.registry``'s shape (archiver#141):
deltas ride the outbox (``src.core.services.fetch_policy``), and this task
republishes the **entire host set** directly, every ``REPUBLISH_PERIOD_SECONDS``.
Consumers replay from ``0-0`` at boot, so their view must be rebuildable from
what the broker still holds. Only while ``ARCHIVER_FETCH_POLICY_PRODUCER`` is
set: dark until flip F1.

The set: one frame per ``Domain`` (a suspended host ``revoked`` with no
interval) and one ``revoked`` frame per ``fetch_policy_tombstones`` row, so a
deleted host's tombstone never ages out (co-core ``FetchPolicyState`` rule 2).
Absence from a set still revokes nothing.

**Generations are read, never drawn** - the ``registry_snapshot`` rule. Every
frame carries its host's stored generation (``build_policy`` refuses one
without), so a set at an unchanged generation is a no-op downstream, and a set
that lost a race with a newer delta is dropped by the consumer's ratchet.

**No retry**: a failed entry is logged and the set continues, and the next
period is the repair. An unpublishable host is skipped with a warning.

**Retention rides the publishes** (``MAXLEN ~``): archiver's grant on this
stream is ``+xadd`` only (CannObserv/broker#93), so it never joins
``trim_topics``. The cap is ``max(resolved, RETAINED_FULL_SETS × set size)``,
and only the complete set may compute that floor (``publish_policy_events``).
Deltas carry the last complete set's cap through ``topic_maxlen``, and none
before the first set: a delta at the bare default would trim the stream back
below the floor.

**Three numbers are mirrored on the broker node** (``src/broker/bus_health.py``):
``DEFAULT_FETCH_POLICY_STREAM_MAXLEN`` as ``LWW_PRODUCER_MAXLEN``,
``RETAINED_FULL_SETS`` as ``LWW_RETAINED_FULL_SETS`` and
``REPUBLISH_PERIOD_SECONDS`` as ``LWW_REPUBLISH_PERIOD_SECONDS``. File on
CannObserv/broker before changing any of them.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import MutableMapping, Sequence
from dataclasses import dataclass

from co_core.effects.bus import BusPublish
from co_core.pure.adapters.bus.envelope import to_wire
from co_core.pure.models.changes import FetchPolicyEmit
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.logging import get_logger
from src.core.models import Domain, FetchPolicyTombstone
from src.core.services.fetch_policy import (
    FETCH_POLICY_TOPIC,
    build_domain_policy,
    build_tombstone,
)

logger = get_logger(__name__)

REPUBLISH_PERIOD_SECONDS = 300
"""Five minutes, Watcher's cron. Broker's ``LWW_REPUBLISH_PERIOD_SECONDS`` is
this number, shared with ``info.watch-status``; it drives the probe's
last-entry-age WARN (3×) and the divisor that reads the set size off the stream
span. Deliberately no env override: one would move the mirror with no commit
in either repo."""

DEFAULT_FETCH_POLICY_STREAM_MAXLEN = 500
"""Watcher's #292 cap, sized against the host set, not the broker's comfort:
a groupless consumer replays every retained entry at boot. Broker's
``LWW_PRODUCER_MAXLEN``. ``ARCHIVER_FETCH_POLICY_STREAM_MAXLEN`` moves the cap
in force with no commit, so setting it obliges a note to CannObserv/broker."""

RETAINED_FULL_SETS = 10
"""The floor's multiplier: the cap never drops below ten complete sets, so a
set larger than the default cannot trim its own earlier frames. Broker's
``LWW_RETAINED_FULL_SETS``."""

MAXLEN_ENV = "ARCHIVER_FETCH_POLICY_STREAM_MAXLEN"


def resolve_fetch_policy_maxlen(raw: str | None, *, floor: int = 1) -> int:
    """Parse the cap defensively; never unbounded, never below ``floor``.

    Watcher's ``resolve_stream_maxlen``: an invalid or non-positive value falls
    back to the default with a warning, and the floor wins over both. An
    explicit value under the floor is the one misconfiguration the floor
    overrides, so it is reported.
    """
    bounded = max(DEFAULT_FETCH_POLICY_STREAM_MAXLEN, floor)
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
class FullSetResult:
    """What one full set did: frames published, and the cap they carried."""

    published: int
    maxlen: int


def build_policy_events(
    domains: Sequence[Domain], tombstones: Sequence[FetchPolicyTombstone]
) -> list[FetchPolicyEmit]:
    """One frame per Domain and per tombstone; an unpublishable host is skipped."""
    events: list[FetchPolicyEmit] = []
    for kind, host, build in [
        *(("domain", d.name, lambda d=d: build_domain_policy(d)) for d in domains),
        *(
            ("tombstone", t.host, lambda t=t: build_tombstone(host=t.host, generation=t.generation))
            for t in tombstones
        ),
    ]:
        try:
            events.append(build())
        except ValidationError:
            logger.warning(
                "skipping unpublishable fetch-policy host", extra={"host": host, "kind": kind}
            )
    return events


async def _collect(session: AsyncSession) -> list[FetchPolicyEmit]:
    domains = (await session.execute(select(Domain).order_by(Domain.name))).scalars().all()
    tombstones = (
        (await session.execute(select(FetchPolicyTombstone).order_by(FetchPolicyTombstone.host)))
        .scalars()
        .all()
    )
    return build_policy_events(domains, tombstones)


async def publish_policy_events(publisher, events: Sequence[FetchPolicyEmit]) -> FullSetResult:
    """XADD each event with the floored cap; per-entry failures are logged and skipped.

    **``events`` must be the complete policy set.** The cap's floor is
    ``len(events) × RETAINED_FULL_SETS``, which is the corpus only while the
    batch *is* the corpus: a partial batch would floor the cap at a fraction of
    the set and trim the set down to it, so a boot replay returns a partial set
    no consumer can tell from a complete one (Watcher #292, CR 1).
    ``tests/core/changes/test_fetch_policy_snapshot_callers.py`` pins the only
    caller to ``publish_full_policy_set``.
    """
    maxlen = resolve_fetch_policy_maxlen(
        os.environ.get(MAXLEN_ENV), floor=len(events) * RETAINED_FULL_SETS
    )
    published = 0
    for event in events:
        try:
            await publisher.execute(
                BusPublish(topic=FETCH_POLICY_TOPIC, fields=to_wire(event), maxlen=maxlen)
            )
        except Exception:
            logger.warning(
                "Fetch-policy entry failed to publish; the next period is the repair",
                extra={"host": event.host, "generation": event.generation},
                exc_info=True,
            )
            continue
        published += 1
    return FullSetResult(published=published, maxlen=maxlen)


async def publish_full_policy_set(
    *, session_factory: async_sessionmaker[AsyncSession], publisher
) -> FullSetResult:
    """Publish the whole set: every Domain, suspended or not, plus every tombstone."""
    async with session_factory() as session:
        events = await _collect(session)
    return await publish_policy_events(publisher, events)


async def run(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    publisher,
    stop_event: asyncio.Event,
    topic_maxlen: MutableMapping[str, int],
    interval: float = REPUBLISH_PERIOD_SECONDS,
) -> None:
    """Publish a full set at startup, then every ``interval`` seconds.

    After each set, ``topic_maxlen[FETCH_POLICY_TOPIC]`` takes its cap: the
    outbox drain reads that mapping per row, so deltas carry the last complete
    set's floor. A cycle that raises is logged and the loop continues.
    """
    while not stop_event.is_set():
        try:
            result = await publish_full_policy_set(
                session_factory=session_factory, publisher=publisher
            )
            topic_maxlen[FETCH_POLICY_TOPIC] = result.maxlen
            logger.info(
                "fetch-policy full set published",
                extra={"published": result.published, "maxlen": result.maxlen},
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("fetch-policy full set failed; next period is the repair")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except TimeoutError:
            pass
