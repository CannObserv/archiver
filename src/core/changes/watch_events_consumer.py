"""``info.watch-events`` ingest: Watcher's facts become notifications (archiver#369, D2).

Design D3: "Watcher monitors and reports; Archiver decides who hears; Notifier
delivers." Watcher outboxes a fact on each observed edge (a change, the edge
into error, the recovery); this group composes it once per subscription that
hears it and records the rows (``src.core.services.notification_dispatch``).
Shadow until the cutover instant T is set (D3); the drain sends what isn't.

Group **``archiver.watch-events``**, consumer **``archiver-watch-events-1``**,
created at ``0``: the facts already on the stream replay into shadow, which is
safe while T is unset. The delivery machinery is ``group_consumer``'s, shared
with ``content.revisions`` and ``content.artifacts``. What is this stream's:

- **Ack after commit.** The unique key makes a redelivery a no-op.
- **An unknown or revoked ``info_item_id`` is ack-and-drop** with a WARNING:
  the registry is the authority on what exists.
- **A malformed ``info_item_id`` is poison** (``content.revisions``'
  precedent), parked on ``info.watch-events.dlq``.
- **``check_rejected`` closes its check-now command** (archiver#370 D3), by
  ``command_id``, first write wins: a redelivered command can mint a second
  ``event_id`` for one rejection. It is check-now's outcome, never a
  notification. An unknown ``command_id`` is ack + WARNING (only Archiver
  issues commands, so one is a fault worth seeing), never a dead letter.
- **Another decoded type is acked** with a WARNING, the ``content.artifacts``
  fall-through. A type co-core doesn't know never reaches here: the shared loop
  parks it as ``undecodable``, and it is reprocessed after a co-core upgrade.
- **Composition never stops the loop.** A diff degrades to its reason, and a
  template falls back to its event's default. Only a database failure leaves
  the fact pending.

**The context.** T and the processor-text reader are process configuration the
lifespan resolves once. It binds them here (:func:`bind_context`) so the loop
and the DLQ triage's reprocess decide a fact identically.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from co_core.pure.adapters.bus.streams import INFO_WATCH_EVENTS, group_name
from co_core.pure.models.changes import (
    ChangeDetectedEvent,
    CheckRejectedEvent,
    WatchErrorEvent,
    WatchRecoveredEvent,
)
from co_core_aio.bus import BusMessage
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.changes import group_consumer
from src.core.changes.backoff import ERROR_BACKOFF_BASE_SECONDS
from src.core.liveness import LoopProgress
from src.core.logging import get_logger
from src.core.services.notification_dispatch import (
    InvalidFactError,
    UnknownInfoItemError,
    record_fact,
)
from src.core.services.watch_check import record_rejection

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from src.core.notifications.diff_loader import TextReader

logger = get_logger(__name__)

# Derived, not spelled (cannobserv#384): ``archiver.watch-events``, the group
# CannObserv/broker#93 grants.
CONSUMER_GROUP = group_name(INFO_WATCH_EVENTS, "archiver")

consumer_enabled = group_consumer.consumer_enabled
WatchEventsConsumer = group_consumer.GroupConsumer

#: Decoded and unusable: redelivery reproduces it.
POISON_ERRORS: tuple[type[BaseException], ...] = (InvalidFactError,)

_WATCH_EVENTS = (ChangeDetectedEvent, WatchErrorEvent, WatchRecoveredEvent)


@dataclass(frozen=True, slots=True)
class DispatchContext:
    """What deciding a fact needs beyond the database: T and the text reader."""

    cutover: datetime | None = None
    text_reader: TextReader | None = None


_context = DispatchContext()


def bind_context(context: DispatchContext) -> None:
    """Set the process's context. The lifespan calls this once, before the loop starts."""
    global _context
    _context = context


def current_context() -> DispatchContext:
    """The bound context; unbound, it is shadow with no reader."""
    return _context


def build_consumer(client: Redis, *, consumer_name: str | None = None) -> WatchEventsConsumer:
    """Build the group reader for ``info.watch-events``."""
    return group_consumer.build_group_consumer(
        client, topic=INFO_WATCH_EVENTS, group=CONSUMER_GROUP, consumer_name=consumer_name
    )


async def ensure_group(consumer: WatchEventsConsumer) -> None:
    """Create the group at ``0`` — see ``group_consumer.ensure_group``."""
    await group_consumer.ensure_group(consumer)


async def handle_message(
    session_factory: async_sessionmaker[AsyncSession], message: BusMessage
) -> bool:
    """Decide one fact. Returns ``True`` if it may be acked.

    Never ``False``: a database failure raises instead, leaving the entry
    pending. Raises :class:`InvalidFactError` (poison) on a malformed item id.
    """
    payload = message.payload
    if isinstance(payload, CheckRejectedEvent):
        await _close_check(session_factory, payload, message.message_id)
        return True
    if not isinstance(payload, _WATCH_EVENTS):
        logger.warning(
            "Ignoring non-watch event on info.watch-events",
            extra={
                "event_type": getattr(payload, "event_type", None),
                "message_id": message.message_id,
            },
        )
        return True

    context = current_context()
    try:
        inserted = await record_fact(
            session_factory, payload, text_reader=context.text_reader, cutover=context.cutover
        )
    except UnknownInfoItemError:
        logger.warning(
            "Dropping watch event for an unknown or revoked info_item",
            extra={
                "info_item_id": payload.info_item_id,
                "event_id": payload.event_id,
                "event_type": payload.event_type,
                "message_id": message.message_id,
            },
        )
        return True
    logger.info(
        "Recorded watch event",
        extra={
            "event_id": payload.event_id,
            "event_type": payload.event_type,
            "info_item_id": payload.info_item_id,
            "rows": inserted,
            "message_id": message.message_id,
        },
    )
    return True


async def _close_check(
    session_factory: async_sessionmaker[AsyncSession], fact: CheckRejectedEvent, message_id: str
) -> None:
    """Record a check-now rejection on its command (archiver#370 D3)."""
    async with session_factory() as session:
        disposition = await record_rejection(session, fact)
        await session.commit()
    extra = {
        "disposition": disposition,
        "command_id": fact.command_id,
        "info_item_id": fact.info_item_id,
        "reason": fact.reason,
        "event_id": fact.event_id,
        "message_id": message_id,
    }
    if disposition == "unknown_command":
        logger.warning("Watch check rejected for a command Archiver never issued", extra=extra)
    else:
        logger.info("Watch check rejection applied", extra=extra)


def _handler(session_factory: async_sessionmaker[AsyncSession]) -> group_consumer.MessageHandler:
    async def _handle(message: BusMessage) -> bool:
        return await handle_message(session_factory, message)

    return _handle


async def consume_once(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    consumer: WatchEventsConsumer,
    count: int = group_consumer.READ_COUNT,
    block_ms: int | None = None,
) -> int:
    """Read and decide up to ``count`` facts. Returns how many settled."""
    return await group_consumer.consume_once(
        consumer=consumer,
        handle=_handler(session_factory),
        poison_errors=POISON_ERRORS,
        count=count,
        block_ms=block_ms,
    )


async def run(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    consumer: WatchEventsConsumer,
    stop_event: asyncio.Event | None = None,
    block_ms: int = group_consumer.READ_BLOCK_MS,
    claim_interval_iterations: int = group_consumer.CLAIM_INTERVAL_ITERATIONS,
    claim_min_idle_ms: int = group_consumer.CLAIM_MIN_IDLE_MS,
    error_backoff_base: float = ERROR_BACKOFF_BASE_SECONDS,
    progress: LoopProgress | None = None,
) -> None:
    """Decide watch events until ``stop_event`` is set."""
    await group_consumer.run(
        consumer=consumer,
        handle=_handler(session_factory),
        poison_errors=POISON_ERRORS,
        stop_event=stop_event,
        block_ms=block_ms,
        claim_interval_iterations=claim_interval_iterations,
        claim_min_idle_ms=claim_min_idle_ms,
        error_backoff_base=error_backoff_base,
        progress=progress,
    )
