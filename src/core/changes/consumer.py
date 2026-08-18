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

Delivery discipline. The loop itself — read, claim, quarantine, ack, back off,
re-arm the group — lives in ``src.core.changes.group_consumer``, shared with the
``content.artifacts`` consumer since archiver#170. What stays here is what is
specific to *this* stream:

- **Ack after commit.** A crash between the two redelivers the message, and the
  ``(info_source_id, content_fingerprint)`` uniqueness makes the retry a no-op
  that emits no second event. A crash the other way round would lose a revision.
- **Unknown ``info_source_id`` is ack-and-drop**, not an error: the registry is
  the authority on what exists, and a fact about something it does not hold is
  not a revision it can record.
- **``SourceRevisionWriteError`` is poison** — the frame decoded and the
  observation is unusable, so redelivery reproduces it exactly. Declared to the
  shared loop as this stream's poison type; it quarantines to
  ``content.revisions.dlq``.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from co_core.pure.adapters.bus.streams import CONTENT_REVISIONS
from co_core.pure.models.changes import SourceRevisionObservedEvent
from co_core_aio.bus import BusMessage
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.changes import group_consumer
from src.core.changes.backoff import ERROR_BACKOFF_BASE_SECONDS
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

# Re-exported so callers and tests keep one import site for this stream's
# consumer, and so the gate's docstring stays where the gate is enforced.
consumer_enabled = group_consumer.consumer_enabled
resolve_consumer_name = group_consumer.resolve_consumer_name
RevisionsConsumer = group_consumer.GroupConsumer

READ_COUNT = group_consumer.READ_COUNT
READ_BLOCK_MS = group_consumer.READ_BLOCK_MS
CLAIM_MIN_IDLE_MS = group_consumer.CLAIM_MIN_IDLE_MS
CLAIM_INTERVAL_ITERATIONS = group_consumer.CLAIM_INTERVAL_ITERATIONS

# Well-formed but unusable: the frame decoded, the observation cannot be
# recorded, and redelivery reproduces it identically.
POISON_ERRORS: tuple[type[BaseException], ...] = (SourceRevisionWriteError,)


def build_consumer(client: Redis, *, consumer_name: str | None = None) -> RevisionsConsumer:
    """Build the group reader for ``content.revisions``."""
    return group_consumer.build_group_consumer(
        client, topic=CONTENT_REVISIONS, group=CONSUMER_GROUP, consumer_name=consumer_name
    )


async def ensure_group(consumer: RevisionsConsumer) -> None:
    """Create the group at ``0`` — see ``group_consumer.ensure_group``."""
    await group_consumer.ensure_group(consumer)


async def quarantine_undecodable(consumer: RevisionsConsumer) -> int:
    """DLQ pending entries that will not decode. Returns how many were moved."""
    return await group_consumer.quarantine_undecodable(consumer)


def _handler(session_factory: async_sessionmaker[AsyncSession]) -> group_consumer.MessageHandler:
    """Bind the session factory into the shared loop's one-message contract."""

    async def _handle(message: BusMessage) -> bool:
        return await handle_message(session_factory, message)

    return _handle


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


async def consume_once(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    consumer: RevisionsConsumer,
    count: int = group_consumer.READ_COUNT,
    block_ms: int | None = None,
) -> int:
    """Read and process up to ``count`` observations. Returns how many settled."""
    return await group_consumer.consume_once(
        consumer=consumer,
        handle=_handler(session_factory),
        poison_errors=POISON_ERRORS,
        count=count,
        block_ms=block_ms,
    )


async def reclaim_stale(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    consumer: RevisionsConsumer,
    min_idle_ms: int = group_consumer.CLAIM_MIN_IDLE_MS,
) -> int:
    """Process entries a dead consumer left pending. Returns how many settled."""
    return await group_consumer.reclaim_stale(
        consumer=consumer,
        handle=_handler(session_factory),
        poison_errors=POISON_ERRORS,
        min_idle_ms=min_idle_ms,
    )


async def run(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    consumer: RevisionsConsumer,
    stop_event: asyncio.Event | None = None,
    block_ms: int = group_consumer.READ_BLOCK_MS,
    claim_interval_iterations: int = group_consumer.CLAIM_INTERVAL_ITERATIONS,
    claim_min_idle_ms: int = group_consumer.CLAIM_MIN_IDLE_MS,
    error_backoff_base: float = ERROR_BACKOFF_BASE_SECONDS,
) -> None:
    """Ingest observed revisions until ``stop_event`` is set."""
    await group_consumer.run(
        consumer=consumer,
        handle=_handler(session_factory),
        poison_errors=POISON_ERRORS,
        stop_event=stop_event,
        block_ms=block_ms,
        claim_interval_iterations=claim_interval_iterations,
        claim_min_idle_ms=claim_min_idle_ms,
        error_backoff_base=error_backoff_base,
    )
