"""``content.revisions`` ingest — Archiver's first consumer role on the bus.

Watcher observes that the content extracted from an InfoSource now has a given
fingerprint and publishes that as a fact; the registry decides what to persist
(archiver#139, step 3 of the #137 epic). Archiver does **not** consume
``content.blobs`` and does **not** extract — Watcher stays the correlator and the
cluster's single extractor. What arrives here is already an observation about a
specific ``info_source_id``.

The write goes through ``src.core.services.source_revision.record_revision``, the
same call ``POST /source-revisions`` makes, so ``source_revision_captured``
payloads on ``info.changes`` are unchanged for existing subscribers — that is a
property of one shared path, not of two paths kept in step.

Delivery discipline:

- **Ack after commit.** A crash between the two redelivers the message, and the
  ``(info_source_id, content_fingerprint)`` uniqueness makes the retry a no-op
  that emits no second event. A crash the other way round would lose a revision.
- **Unknown ``info_source_id`` is ack-and-drop**, not an error: the registry is
  the authority on what exists, and a fact about something it does not hold is
  not a revision it can record.
- **Undecodable frames are quarantined**, not retried forever. See
  ``quarantine_undecodable`` for why that needs a raw pass over the PEL.
"""

from __future__ import annotations

import asyncio
import os
import socket
from dataclasses import dataclass
from typing import TYPE_CHECKING

from co_core.pure.adapters.bus.exceptions import BusMessageAnomaly
from co_core.pure.adapters.bus.streams import CONTENT_REVISIONS
from co_core.pure.models.changes import SourceRevisionObservedEvent
from co_core_aio.bus import AsyncBusConsumer, BusMessage, from_wire
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.changes.backoff import (
    ERROR_BACKOFF_BASE_SECONDS,
    ERROR_LOG_EVERY,
    error_backoff_seconds,
)
from src.core.logging import get_logger
from src.core.services.source_revision import (
    RevisionFacts,
    SourceRevisionWriteError,
    UnknownInfoSourceError,
    parse_info_source_id,
    record_revision,
    validate_fingerprint,
)

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = get_logger(__name__)

# One group per consuming service — the broadcast posture for a fact stream. The
# name is the wire contract with the broker's monitoring (``XPENDING`` lag lives
# under it), so it is as fixed as the stream name.
CONSUMER_GROUP = "archiver.revisions"

# Read one at a time. ``AsyncBusConsumer.read`` decodes inside the call, so a
# poison frame in a ``count > 1`` batch raises before the well-formed messages
# are returned; at one per read, the frame that raised is unambiguous. Production
# volume is a handful of WatchedItems, so batching buys nothing worth that.
READ_COUNT = 1
READ_BLOCK_MS = 5_000

# Reclaim entries a consumer took and never acked (it died mid-message). Long
# enough that it never races a live consumer's in-flight message.
CLAIM_MIN_IDLE_MS = 60_000
CLAIM_INTERVAL_ITERATIONS = 12
CLAIM_COUNT = 10
# Bound the quarantine scan so a pathological PEL cannot hold the loop forever;
# at CLAIM_COUNT per pass this covers 1000 pending entries, and the residue is
# logged rather than silently skipped.
MAX_QUARANTINE_PASSES = 100

_TRUTHY = frozenset({"1", "true", "yes", "on"})


def consumer_enabled(raw: str | None) -> bool:
    """Whether ``ARCHIVER_BUS_CONSUMER`` opts this process into the group.

    A gate the publisher never needed. Producing to the bus from a stray process
    is noisy; *consuming* removes messages from ``archiver.revisions``, so any
    process that sources ``/etc/archiver/.env`` — an agent shell, a one-off
    script, a debug run — would join as a competing consumer and silently
    swallow revisions into whatever database it happens to hold. Presence of
    ``ARCHIVER_REDIS_URL`` is therefore not sufficient authority; only
    ``deploy/archiver.service`` sets this, and it must never appear in an env
    file (the ``ARCHIVER_ALLOW_PRODUCTION_DB`` precedent).
    """
    return (raw or "").strip().lower() in _TRUTHY


def resolve_consumer_name() -> str:
    """Name this reader within the group — ``{hostname}:{pid}``.

    One process per host today (``deploy/archiver.service`` runs uvicorn with no
    ``--workers``), but a group member must be uniquely named for ``XAUTOCLAIM``
    to distinguish a dead consumer's pending entries from a live one's.
    """
    return f"{socket.gethostname()}:{os.getpid()}"


@dataclass(frozen=True, slots=True)
class RevisionsConsumer:
    """The group reader plus the two things every recovery path also needs.

    ``AsyncBusConsumer`` does not expose its own consumer name, and the raw
    ``XAUTOCLAIM`` in ``quarantine_undecodable`` has to claim under exactly that
    name. Bundling the three rather than reaching into the driver's internals —
    they always travel together anyway.
    """

    bus: AsyncBusConsumer
    name: str
    client: Redis


def build_consumer(client: Redis, *, consumer_name: str | None = None) -> RevisionsConsumer:
    """Build the group reader for ``content.revisions``."""
    name = consumer_name or resolve_consumer_name()
    return RevisionsConsumer(
        bus=AsyncBusConsumer(client, topic=CONTENT_REVISIONS, group=CONSUMER_GROUP, consumer=name),
        name=name,
        client=client,
    )


async def ensure_group(consumer: RevisionsConsumer) -> None:
    """Create the group at ``0``, not ``$``.

    ``$`` delivers only what is published after group creation, so anything
    already on the stream when this service first starts is dropped — which is
    exactly the window the epic's "land the consumer before Watcher removes its
    POST" ordering exists to close. Replay from the beginning is safe here
    because redelivery is an idempotent no-op, so ``0`` costs a few wasted
    lookups and buys the ordering guarantee.
    """
    await consumer.bus.ensure_group(start_id="0")


def _facts_from(event: SourceRevisionObservedEvent) -> RevisionFacts:
    """Map the observation onto the registry's columns.

    ``extracted_fingerprint`` → ``content_fingerprint``: the name differs on the
    wire because it must never be cross-matched with ``BlobAvailableEvent``'s
    raw-bytes ``content_fingerprint`` (cannobserv#301), but within the registry
    the extracted fingerprint *is* the revision's identity.

    ``blob_uri`` → ``content_cache_uri`` and ``blob_expires_at`` →
    ``content_cache_expires_at``: deliberately the cache columns. The blob is a
    VM-local ``file://`` on Replicator's host with a TTL whose clock runs from
    last fetch reference, not last read. Durable bytes are what RepSpec
    replication is for. A missing expiry records absence rather than a TTL
    guessed from Replicator's policy.

    Raises:
        SourceRevisionWriteError: the observation names an unusable
            ``info_source_id`` or fingerprint — poison, since redelivery yields
            the identical values.
    """
    return RevisionFacts(
        info_source_id=parse_info_source_id(event.info_source_id),
        content_fingerprint=validate_fingerprint(event.extracted_fingerprint),
        captured_at=event.captured_at,
        content_size_bytes=event.content_size_bytes,
        content_media_type=event.content_media_type,
        content_cache_uri=event.blob_uri,
        content_cache_expires_at=event.blob_expires_at,
        source_media_type=event.source_media_type,
        spec_fingerprint=event.spec_fingerprint,
        command_id=event.command_id,
    )


async def handle_message(
    session_factory: async_sessionmaker[AsyncSession], message: BusMessage
) -> bool:
    """Persist one observation. Returns ``True`` if the message may be acked.

    ``False`` means the message must stay pending for redelivery — reserved for
    failures that a retry could resolve (the database being down). A message the
    registry has *decided* about — recorded, deduped, or dropped as unknown — is
    ackable even though nothing may have been written.

    Raises:
        SourceRevisionWriteError: the observation is well-formed but unusable
            (a misspelled fingerprint). The caller quarantines it; a retry would
            fail identically.
    """
    payload = message.payload
    if not isinstance(payload, SourceRevisionObservedEvent):
        # Another event type on this stream: the registry has no opinion on it.
        # Ack rather than quarantine — it decoded fine, it just is not ours.
        logger.info(
            "Ignoring non-observation event on content.revisions",
            extra={"event_type": getattr(payload, "event_type", None)},
        )
        return True

    facts = _facts_from(payload)

    async with session_factory() as session:
        try:
            row, inserted = await record_revision(session, facts)
        except UnknownInfoSourceError:
            # Ack and drop. The registry is the authority on what exists, so this
            # is a fact about something outside it — not poison, and not
            # something redelivery can fix.
            logger.warning(
                "Dropping observation for unknown info_source",
                extra={
                    "info_source_id": str(facts.info_source_id),
                    "content_fingerprint": facts.content_fingerprint,
                    "message_id": message.message_id,
                },
            )
            return True
        # Read the id BEFORE the commit closes over it. With an
        # expire_on_commit=True factory the row is expired and detached by the
        # time the log below runs, and the refresh it triggers raises *after*
        # the commit and *before* the ack — the write lands, the message is
        # never acked, and every redelivery fails identically (CR round 1,
        # finding 3).
        revision_id = str(row.source_revision_id)
        await session.commit()

    logger.info(
        "Recorded observed revision" if inserted else "Observed revision already recorded",
        extra={
            "info_source_id": str(facts.info_source_id),
            "source_revision_id": revision_id,
            "content_fingerprint": facts.content_fingerprint,
            "inserted": inserted,
            "message_id": message.message_id,
        },
    )
    return True


async def _process(
    session_factory: async_sessionmaker[AsyncSession],
    consumer: RevisionsConsumer,
    message: BusMessage,
) -> bool:
    """Handle one decoded message and settle it if the outcome is terminal.

    Returns whether the message was settled — acked after a successful write, or
    dead-lettered when the observation can never be used. The ack strictly follows the commit
    inside ``handle_message``; a failure in between leaves the entry pending and
    the next delivery repeats an idempotent write.
    """
    try:
        ackable = await handle_message(session_factory, message)
    except SourceRevisionWriteError as exc:
        logger.error(
            "Quarantining unusable observation",
            extra={"message_id": message.message_id, "error": repr(exc)},
        )
        await consumer.bus.dead_letter(message.message_id, dict(message.fields))
        return True

    if ackable:
        await consumer.bus.ack(message.message_id)
    return ackable


async def quarantine_undecodable(consumer: RevisionsConsumer) -> int:
    """DLQ pending entries that will not decode. Returns how many were moved.

    ``AsyncBusConsumer.read`` decodes inside the call, so ``from_wire`` raises
    *before* any message id reaches the caller — there is nothing to hand
    ``dead_letter``, and the entry is already in the group's PEL where a
    subsequent read or claim hits it again identically. Left alone that is an
    unbounded crash-backoff loop over one bad frame, the failure the publisher's
    build-phase dead-letter exists to prevent (archiver#107).

    So the recovery goes back to the raw stream: claim the group's pending
    entries, re-attempt the decode per entry, and route only the ones that fail
    to ``content.revisions.dlq``. Entries that decode are left pending — they are
    picked up by the next read or by ``reclaim_stale``.

    The scan follows ``XAUTOCLAIM``'s cursor to the end of the PEL rather than
    stopping at the first ``CLAIM_COUNT`` window: after a backlog (a DB outage,
    say) the poison frame can sit well past entry ten, and a single-window scan
    would leave it there for as many passes as it takes the window to advance
    (CR round 1, finding 12).

    ``min_idle_time=0`` claims regardless of age, and following the cursor means
    the scan is **bounded only by the pass ceiling** — up to
    ``MAX_QUARANTINE_PASSES * CLAIM_COUNT`` entries, not the single window it
    took before. With one process per host (what ``deploy/archiver.service``
    runs, no ``--workers``) that is free. With two, one poison frame would pull
    the *whole* group's in-flight PEL to a single worker rather than a slice of
    it. **A multi-consumer deployment must raise ``min_idle_time`` above the
    expected per-message processing time** before adding workers — that is the
    change this constant is waiting on, recorded here because this is where it
    would be made (CR round 2, finding 17).
    """
    quarantined = 0
    cursor = "0-0"
    for _ in range(MAX_QUARANTINE_PASSES):
        next_cursor, entries, _deleted = await consumer.client.xautoclaim(
            CONTENT_REVISIONS,
            CONSUMER_GROUP,
            consumer.name,
            min_idle_time=0,
            start_id=cursor,
            count=CLAIM_COUNT,
        )
        for entry_id, raw_fields in entries:
            message_id = _as_str(entry_id)
            fields = {_as_str(k): _as_str(v) for k, v in raw_fields.items()}
            try:
                from_wire(fields, topic=CONTENT_REVISIONS, message_id=message_id)
            except BusMessageAnomaly as exc:
                logger.error(
                    "Dead-lettering undecodable frame",
                    extra={
                        "message_id": message_id,
                        "topic": CONTENT_REVISIONS,
                        "error": repr(exc),
                    },
                )
                await consumer.bus.dead_letter(message_id, fields)
                quarantined += 1
        cursor = _as_str(next_cursor)
        # "0-0" is XAUTOCLAIM's end-of-PEL sentinel; an empty page ends it too.
        if cursor == "0-0" or not entries:
            break
    else:
        logger.warning(
            "Quarantine scan hit its pass ceiling; pending entries remain unscanned",
            extra={"passes": MAX_QUARANTINE_PASSES, "quarantined": quarantined},
        )
    return quarantined


def _as_str(value: bytes | str) -> str:
    """Redis returns bytes unless the client decodes responses; accept both."""
    return value.decode() if isinstance(value, bytes) else value


async def consume_once(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    consumer: RevisionsConsumer,
    count: int = READ_COUNT,
    block_ms: int | None = None,
) -> int:
    """Read and process up to ``count`` messages. Returns how many were settled.

    *Settled* covers every terminal disposition — recorded, deduped, dropped as
    unknown, or quarantined — rather than only the ones that wrote a row; the
    count exists to pace the loop, and all four mean "do not redeliver this"
    (CR round 1, finding 13).

    A decode failure is not raised at the caller: the offending frame is
    quarantined and this call returns 0, so the loop keeps its cadence and the
    next iteration reads past it.
    """
    try:
        messages = await consumer.bus.read(count=count, block_ms=block_ms)
    except BusMessageAnomaly:
        await quarantine_undecodable(consumer)
        return 0

    settled = 0
    for message in messages:
        try:
            if await _process(session_factory, consumer, message):
                settled += 1
        except Exception:
            # Un-acked on purpose: the entry stays in the PEL and is redelivered.
            logger.exception(
                "Failed to process observation; leaving it pending",
                extra={"message_id": message.message_id},
            )
    return settled


async def reclaim_stale(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    consumer: RevisionsConsumer,
    min_idle_ms: int = CLAIM_MIN_IDLE_MS,
) -> int:
    """Process entries a dead consumer left pending. Returns how many were settled.

    Without this, a crash between read and ack parks the message in that
    consumer's PEL permanently — the process that owned it never comes back
    under the same name (the name carries its pid).
    """
    try:
        messages = await consumer.bus.claim_stale(min_idle_ms=min_idle_ms, count=CLAIM_COUNT)
    except BusMessageAnomaly:
        await quarantine_undecodable(consumer)
        return 0

    settled = 0
    for message in messages:
        try:
            if await _process(session_factory, consumer, message):
                settled += 1
        except Exception:
            logger.exception(
                "Failed to process reclaimed observation; leaving it pending",
                extra={"message_id": message.message_id},
            )
    return settled


async def run(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    consumer: RevisionsConsumer,
    stop_event: asyncio.Event | None = None,
    block_ms: int = READ_BLOCK_MS,
    claim_interval_iterations: int = CLAIM_INTERVAL_ITERATIONS,
    claim_min_idle_ms: int = CLAIM_MIN_IDLE_MS,
    error_backoff_base: float = ERROR_BACKOFF_BASE_SECONDS,
) -> None:
    """Loop until ``stop_event`` is set, ingesting observed revisions.

    The blocking read paces the loop, so there is no idle sleep; only a failing
    iteration backs off (escalating, capped, logged every
    ``ERROR_LOG_EVERY``-th so a sustained broker outage cannot flood the
    journal). ``asyncio.CancelledError`` propagates for shutdown; everything else
    is logged and the loop continues.

    **Group creation is inside the loop, and any failure re-arms it** (CR round 1,
    finding 1). Hoisting the ``ensure_group`` call above the loop looks tidier and
    breaks two ways that are hard to see afterwards:

    - A broker that is down at *startup* kills the task outright. That is not
      hypothetical — ``archiver.service`` orders after ``redis-server`` only
      softly (``Wants=``), on the reasoning that the outbox tolerates a late
      broker; the consumer would not have.
    - Flushing the stream destroys its groups, after which every read raises
      ``NOGROUP`` forever. archiver#139's own deploy plan prescribes flushing
      streams, and ``deploy/README.md`` treats it as routine, so this is a state
      operators are *instructed* to produce.

    Both end the same way — no ingestion, silently, while the stream keeps
    growing. ``ensure_group`` is idempotent (``BUSYGROUP`` is swallowed), so
    re-asserting costs one round trip on the pass after a failure and nothing at
    all on the happy path.
    """
    stop_event = stop_event or asyncio.Event()
    logger.info(
        "content.revisions consumer starting",
        extra={"group": CONSUMER_GROUP, "topic": CONTENT_REVISIONS},
    )

    iteration = 0
    consecutive_failures = 0
    group_ready = False
    while not stop_event.is_set():
        try:
            if not group_ready:
                await ensure_group(consumer)
                group_ready = True
            await consume_once(
                session_factory=session_factory, consumer=consumer, block_ms=block_ms
            )
            iteration += 1
            if claim_interval_iterations and iteration % claim_interval_iterations == 0:
                await reclaim_stale(
                    session_factory=session_factory,
                    consumer=consumer,
                    min_idle_ms=claim_min_idle_ms,
                )
            if consecutive_failures:
                # Positive recovery signal at the same filter level as the
                # failures, so both edges of an incident are visible.
                logger.warning(
                    "content.revisions consumer recovered",
                    extra={"after_failures": consecutive_failures},
                )
            consecutive_failures = 0
            continue
        except asyncio.CancelledError:
            raise
        except Exception:
            consecutive_failures += 1
            # Re-arm group creation. The cheapest correct response to *any*
            # failure, because the two states that need it — broker unreachable,
            # group destroyed by a flush — are not distinguishable from the
            # exception type in a way worth branching on, and re-asserting an
            # existing group is a no-op.
            group_ready = False
            if consecutive_failures == 1 or consecutive_failures % ERROR_LOG_EVERY == 0:
                logger.exception(
                    "content.revisions consumer loop error; backing off",
                    extra={"consecutive_failures": consecutive_failures},
                )

        delay = error_backoff_seconds(consecutive_failures, error_backoff_base)
        await asyncio.wait(
            [asyncio.create_task(stop_event.wait())],
            timeout=delay,
            return_when=asyncio.FIRST_COMPLETED,
        )
