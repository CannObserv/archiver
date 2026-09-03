"""``content.artifacts`` ingest — the return leg of ``content.replicate``.

Archiver issues replication (archiver#169) and this is where the outcome lands
(archiver#170). Both facts share the stream, which is deliberate: an issuer wants
one consumer group seeing success and failure, because "did this command close?"
is one question.

The delivery machinery — read, claim, quarantine, ack, back off, re-arm the group
— is ``src.core.changes.group_consumer``, shared with the ``content.revisions``
ingest. What is specific to this stream:

- **A success may arrive more than once, by design** (MUST-4 / T4). A redelivery
  that finds matching bytes at the destination no-ops and re-emits the same
  ``public_url``. The writeback is idempotent, so a repeat costs a duplicate
  assignment of identical values and nothing else.
- **An unknown ``command_id`` is ack-and-drop**, not poison: the registry is the
  authority on what it issued, and a fact about anything else is not something
  redelivery can fix. The same posture ``content.revisions`` takes for an unknown
  ``info_source_id``.
- **There is no poison class here.** A frame either decodes (and names a command
  the registry holds or does not) or it does not decode at all, and the second
  case is handled by the shared quarantine path before a handler ever sees it.
  A database failure raises and leaves the entry pending, which is redelivery
  rather than loss.

The reaper for the silent case — a command that produces *neither* fact — is
``src.core.services.replication_writeback.reap_open_commands``, run on its own
timer rather than from this loop: it must fire whether or not any message
arrives, which is precisely the condition it exists to detect.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from co_core.pure.adapters.bus.streams import CONTENT_ARTIFACTS, group_name
from co_core.pure.models.changes import ReplicationCompleteEvent, ReplicationFailedEvent
from co_core_aio.bus import BusMessage
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.changes import group_consumer
from src.core.changes.backoff import ERROR_BACKOFF_BASE_SECONDS
from src.core.logging import get_logger
from src.core.services.replication_writeback import (
    UnknownCommandError,
    apply_failure,
    apply_success,
)

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = get_logger(__name__)

# One group per consuming service — the broadcast posture for a fact stream, and
# a wire contract with the broker's monitoring (``XPENDING`` lag lives under it).
# Derived, not spelled: co-core's ``<service>.<stream-suffix>`` convention went
# 0/5 across the cluster while it lived only as a docstring beside a free-string
# ``group`` parameter (cannobserv#384). Since co-core >=0.13.1 it is an
# importable helper, so deriving makes drift impossible rather than merely
# discouraged. Evaluates to the string already on the broker, so this is a
# no-op at runtime.
CONSUMER_GROUP = group_name(CONTENT_ARTIFACTS, "archiver")

# Re-exported so this stream has one import site, matching ``consumer.py``.
consumer_enabled = group_consumer.consumer_enabled
ArtifactsConsumer = group_consumer.GroupConsumer


def build_consumer(client: Redis, *, consumer_name: str | None = None) -> ArtifactsConsumer:
    """Build the group reader for ``content.artifacts``."""
    return group_consumer.build_group_consumer(
        client, topic=CONTENT_ARTIFACTS, group=CONSUMER_GROUP, consumer_name=consumer_name
    )


async def ensure_group(consumer: ArtifactsConsumer) -> None:
    """Create the group at ``0`` — see ``group_consumer.ensure_group``."""
    await group_consumer.ensure_group(consumer)


async def handle_message(
    session_factory: async_sessionmaker[AsyncSession], message: BusMessage
) -> bool:
    """Apply one outcome fact. Returns ``True`` if the message may be acked.

    ``False`` is never returned: every decoded outcome is a decision the registry
    can make — applied, or dropped as being about a command it never issued. A
    failure a retry *could* fix (the database being down) raises instead, leaving
    the entry pending.
    """
    payload = message.payload

    if isinstance(payload, ReplicationCompleteEvent):
        return await _apply(
            session_factory,
            message,
            lambda session: apply_success(
                session,
                command_id=payload.command_id,
                public_url=payload.public_url,
                occurred_at=payload.occurred_at,
            ),
            command_id=payload.command_id,
        )

    if isinstance(payload, ReplicationFailedEvent):
        return await _apply(
            session_factory,
            message,
            lambda session: apply_failure(
                session,
                command_id=payload.command_id,
                reason=payload.reason,
                terminal=payload.terminal,
                attempts=payload.attempts,
                detail=payload.detail,
                occurred_at=payload.occurred_at,
            ),
            command_id=payload.command_id,
        )

    # Another event type on this stream: the registry has no opinion on it. Ack
    # rather than quarantine — it decoded fine, it just is not ours.
    logger.info(
        "Ignoring non-outcome event on content.artifacts",
        extra={"event_type": getattr(payload, "event_type", None)},
    )
    return True


async def _apply(
    session_factory: async_sessionmaker[AsyncSession],
    message: BusMessage,
    write: Callable[[AsyncSession], Awaitable[object]],
    *,
    command_id: str,
) -> bool:
    """Run one writeback in its own transaction, committing before the ack."""
    async with session_factory() as session:
        try:
            await write(session)
        except UnknownCommandError:
            logger.warning(
                "Dropping outcome for a command this registry never issued",
                extra={"command_id": command_id, "message_id": message.message_id},
            )
            return True
        await session.commit()
    return True


def _handler(session_factory: async_sessionmaker[AsyncSession]) -> group_consumer.MessageHandler:
    """Bind the session factory into the shared loop's one-message contract."""

    async def _handle(message: BusMessage) -> bool:
        return await handle_message(session_factory, message)

    return _handle


async def consume_once(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    consumer: ArtifactsConsumer,
    count: int = group_consumer.READ_COUNT,
    block_ms: int | None = None,
) -> int:
    """Read and process up to ``count`` outcome facts. Returns how many settled."""
    return await group_consumer.consume_once(
        consumer=consumer,
        handle=_handler(session_factory),
        count=count,
        block_ms=block_ms,
    )


async def reclaim_stale(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    consumer: ArtifactsConsumer,
    min_idle_ms: int = group_consumer.CLAIM_MIN_IDLE_MS,
) -> int:
    """Process entries a dead consumer left pending. Returns how many settled."""
    return await group_consumer.reclaim_stale(
        consumer=consumer,
        handle=_handler(session_factory),
        min_idle_ms=min_idle_ms,
    )


async def run(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    consumer: ArtifactsConsumer,
    stop_event: asyncio.Event | None = None,
    block_ms: int = group_consumer.READ_BLOCK_MS,
    claim_interval_iterations: int = group_consumer.CLAIM_INTERVAL_ITERATIONS,
    claim_min_idle_ms: int = group_consumer.CLAIM_MIN_IDLE_MS,
    error_backoff_base: float = ERROR_BACKOFF_BASE_SECONDS,
) -> None:
    """Apply replication outcomes until ``stop_event`` is set."""
    await group_consumer.run(
        consumer=consumer,
        handle=_handler(session_factory),
        stop_event=stop_event,
        block_ms=block_ms,
        claim_interval_iterations=claim_interval_iterations,
        claim_min_idle_ms=claim_min_idle_ms,
        error_backoff_base=error_backoff_base,
    )
