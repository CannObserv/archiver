"""The ``content.fetch-policy`` producer's delta half (archiver#366).

Archiver took over Watcher's producer at flip F1 (archiver#438): one ``FetchPolicyState`` per
host, last-write-wins, consumed by Replicator. Same shape as ``info.registry``
(archiver#141): a delta through ``changes_outbox`` in the transaction that
changes the host, plus a full set published directly on a timer
(``src.core.changes.fetch_policy_snapshot``). This module owns the delta half
and the one builder both halves share.

**Unit-only.** ``ARCHIVER_FETCH_POLICY_PRODUCER`` is set only in
``deploy/archiver.service`` (since flip F1, archiver#438), never in an env file
(the ``ARCHIVER_BUS_CONSUMER`` precedent): a second writer would fight it and no
ACL refuses two (CannObserv/broker#93). Where it is off (every dev and test
process), generations still advance with every change, and nothing reaches the
outbox.

**The frame** is ``(revoked, min_interval_seconds if live)``. A suspended host
(``domain_suspended``, the predicate ``info.registry`` resolves ``active=false``
by, so the two streams cannot disagree) publishes ``revoked=True`` with no
interval, never a fake number. A deleted host publishes the same, from
``fetch_policy_tombstones``.

**Generations** (co-core ``FetchPolicyState``'s three producer obligations):

1. **On every frame**, tombstones and full sets included. ``FetchPolicyEmit``
   accepts ``None`` until cannobserv#579, and a frame without one is dropped
   silently once the host holds an ordered frame - so ``build_policy`` refuses it.
2. **Drawn atomically**: ``UPDATE … SET fetch_policy_generation =
   nextval(…) RETURNING``, never read-modify-write.
3. **Never backwards for a host**: one sequence for every host, deletes
   included. A draw is issued only once the row is this transaction's - locked,
   or inserted - because a column default is evaluated when an ``INSERT … ON
   CONFLICT`` forms its tuple, *before* it waits on a concurrent delete of the
   same name. A re-add racing that delete would then hold a value below the
   tombstone, and its live frame would be dropped for good.

A value is drawn only when the frame changes, or the row is new. Notes and the
cadence never draw; neither does an interval edit on a suspended host.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import UTC, datetime

from co_core.pure.adapters.bus.streams import CONTENT_FETCH_POLICY
from co_core.pure.models.changes import FetchPolicyEmit
from pydantic import ValidationError
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

from src.core.logging import get_logger
from src.core.models import ChangesOutboxRow, Domain, FetchPolicyTombstone
from src.core.models.domain import FETCH_POLICY_GENERATION_SEQ
from src.core.services.registry_announcement import domain_suspended

logger = get_logger(__name__)

FETCH_POLICY_TOPIC = CONTENT_FETCH_POLICY

PRODUCER_ENV = "ARCHIVER_FETCH_POLICY_PRODUCER"
"""The F1 switch. Set only in ``deploy/archiver.service``; never in an env file."""

_TRUTHY = frozenset({"1", "true", "yes", "on"})

PolicyFrame = tuple[bool, float | None]


def producer_enabled(environ: Mapping[str, str] = os.environ) -> bool:
    """Whether this process produces ``content.fetch-policy``.

    Read on every call, so a test (or the dev server) flips it without a reload.
    """
    return (environ.get(PRODUCER_ENV) or "").strip().lower() in _TRUTHY


def policy_frame(domain: Domain) -> PolicyFrame:
    """What the host's frame says: ``(revoked, min_interval_seconds or None)``."""
    if domain_suspended(domain):
        return True, None
    return False, domain.min_interval_seconds


def build_policy(
    *, host: str, generation: int, min_interval_seconds: float | None, revoked: bool
) -> FetchPolicyEmit:
    """The one builder for both emit paths; refuses a frame without a generation.

    Raises ``TypeError`` for a non-integer generation and ``ValueError`` (a
    ``ValidationError`` included) for anything co-core refuses.
    """
    if isinstance(generation, bool) or not isinstance(generation, int):
        raise TypeError(
            f"a content.fetch-policy frame needs an integer generation, got {generation!r}"
        )
    return FetchPolicyEmit(
        occurred_at=datetime.now(UTC),
        host=host,
        min_interval_seconds=min_interval_seconds,
        revoked=revoked,
        generation=generation,
    )


def build_domain_policy(domain: Domain) -> FetchPolicyEmit:
    """The host's frame at its stored generation."""
    revoked, interval = policy_frame(domain)
    return build_policy(
        host=domain.name,
        generation=domain.fetch_policy_generation,
        min_interval_seconds=interval,
        revoked=revoked,
    )


def build_tombstone(*, host: str, generation: int) -> FetchPolicyEmit:
    """A deleted host's frame: revoked, no interval."""
    return build_policy(host=host, generation=generation, min_interval_seconds=None, revoked=True)


def _queue(session: AsyncSession, host: str, build) -> None:
    """Add the outbox row while the producer is enabled; skip an unbuildable host.

    Watcher's rule: one unpublishable host never fails the write that changed
    it. The full set skips it too, with the same warning.
    """
    if not producer_enabled():
        return
    try:
        event = build()
    except ValidationError:
        logger.warning(
            "skipping unpublishable fetch-policy host", extra={"host": host, "kind": "delta"}
        )
        return
    session.add(ChangesOutboxRow(topic=FETCH_POLICY_TOPIC, payload=event.model_dump(mode="json")))


async def announce_domain(session: AsyncSession, domain: Domain) -> int:
    """Draw the host's next generation, clear its tombstone, queue its frame.

    The caller holds the row (locked, or inserted by this transaction) and has
    flushed the change; it commits. Returns the generation drawn.
    """
    generation = (
        await session.execute(
            update(Domain)
            .where(Domain.id == domain.id)
            .values(fetch_policy_generation=FETCH_POLICY_GENERATION_SEQ.next_value())
            .returning(Domain.fetch_policy_generation)
            .execution_options(synchronize_session=False)
        )
    ).scalar_one()
    set_committed_value(domain, "fetch_policy_generation", generation)
    await session.execute(
        delete(FetchPolicyTombstone).where(FetchPolicyTombstone.host == domain.name)
    )
    _queue(session, domain.name, lambda: build_domain_policy(domain))
    return generation


async def announce_domain_deleted(session: AsyncSession, name: str) -> int:
    """Record ``name``'s tombstone at a freshly drawn generation and queue it.

    Call in the delete's transaction; the caller commits. Returns the generation.
    """
    generation = (
        await session.execute(select(FETCH_POLICY_GENERATION_SEQ.next_value()))
    ).scalar_one()
    stmt = pg_insert(FetchPolicyTombstone).values(
        host=name, generation=generation, revoked_at=datetime.now(UTC)
    )
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=[FetchPolicyTombstone.host],
            set_={"generation": stmt.excluded.generation, "revoked_at": stmt.excluded.revoked_at},
        )
    )
    _queue(session, name, lambda: build_tombstone(host=name, generation=generation))
    return generation
