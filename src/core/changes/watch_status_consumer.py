"""``info.watch-status`` tail — the return leg of the announcement channel.

Watcher broadcasts the generation it has *applied* plus scheduler state and
observation freshness (watcher#264); Archiver tails it into the persisted
``watch_status`` cache and renders the watched-item panel from local state
(archiver#151). Groupless by stream kind: this is config/state, LWW per
``info_item_id``, so every consumer needs every message and a consumer group
here would accumulate a PEL nothing drains — the ``AsyncBusTailReader`` shape,
not the ``AsyncBusConsumer`` + group shape of ``consumer.py``.

**Resume is a persisted cursor, not a full replay.** The reader has no group
and therefore no server-side delivery cursor; ``bus_tail_cursors`` carries the
last applied id, advanced in the same transaction as the apply, so boot is a
delta and a crash between write and cursor is impossible. A cold start (no
cursor row) replays from ``0-0``.

**No DLQ, matching ``content.fetch-policy`` — which makes "retry forever" a
stall, not a safety net.** With no group there is no PEL to quarantine from,
and the cursor only advances on a successful apply, so any message that can
never succeed would spin indefinitely and silently. Two skip paths exist for
that reason: a frame that will not *decode*, and a decoded message the registry
can never *write* (``_UNAPPLIABLE_DB_ERRORS``). Both are logged and stepped
past durably, so a restart does not re-hit them; on an LWW stream the
producer's periodic republish is what restores whatever a skip dropped.
Everything else still rewinds and retries.

**Gate: bus-URL presence only — deliberately not ``ARCHIVER_BUS_CONSUMER``.**
That gate exists because a group consumer *removes* messages from
``archiver.revisions``; a stray process joining the group steals from
production's PEL. A groupless tail removes nothing, so a stray tail is
harmless, and the dormant-without-``ARCHIVER_REDIS_URL`` rule is sufficient.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from co_core.pure.adapters.bus.exceptions import BusMessageAnomaly
from co_core.pure.models.changes import WatchStatusState
from co_core_aio.bus import AsyncBusTailReader, BusMessage
from sqlalchemy.exc import DataError, IntegrityError, NotSupportedError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.changes.backoff import (
    ERROR_BACKOFF_BASE_SECONDS,
    ERROR_LOG_EVERY,
    error_backoff_seconds,
)
from src.core.changes.diagnostics import error_text
from src.core.logging import get_logger
from src.core.services.watch_status import (
    WATCH_STATUS_TOPIC,
    advance_cursor,
    apply_watch_status,
    read_cursor,
)

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = get_logger(__name__)

# One frame per read: a poison frame in a count > 1 batch discards the decoded
# prefix (the tail reader's cursor only advances on a fully-decoded batch), and
# recovery then needs the drain-then-seek sequence its docstring prescribes.
# At count=1 the frame that raised is unambiguous and seek is safe immediately.
READ_COUNT = 1
READ_BLOCK_MS = 5_000

# Failures redelivery cannot resolve: the frame decoded, but the registry can
# never write it — a value outside a column's domain, a constraint it violates,
# a statement the server rejects. Retrying reproduces them exactly, and with no
# DLQ and a cursor that only advances on a successful apply, the loop would spin
# on one frame **forever** — a silent, total stall of the stream that exists to
# detect silent drift (CR round 1, finding 1). Skipping is safe here in a way it
# would not be on a fact stream: this is last-write-wins state, so the
# producer's periodic republish is the repair.
#
# Deliberately an allow-list, not a catch-all. An *unclassified* failure keeps
# rewinding and logging, because the plausible cause is a bug of ours, and a
# code fault that silently swallowed every message would be far worse than a
# stall an operator can see.
_UNAPPLIABLE_DB_ERRORS = (DataError, IntegrityError, NotSupportedError, ProgrammingError)


async def resolve_start_id(session_factory: async_sessionmaker[AsyncSession]) -> str:
    """The persisted resume point, or ``0-0`` for a cold start."""
    async with session_factory() as session:
        cursor = await read_cursor(session, WATCH_STATUS_TOPIC)
    return cursor or "0-0"


def build_reader(client: Redis, *, start_id: str = "0-0") -> AsyncBusTailReader:
    """Build the groupless tail reader for ``info.watch-status``."""
    return AsyncBusTailReader(client, topic=WATCH_STATUS_TOPIC, start_id=start_id)


async def handle_message(
    session_factory: async_sessionmaker[AsyncSession], message: BusMessage
) -> str:
    """Apply one decoded message and advance the cursor, atomically.

    Returns the disposition for logging. A payload of another event type on
    this stream is skipped-but-advanced: it decoded fine, it just is not ours,
    and the vocabulary is expected to grow.
    """
    payload = message.payload
    async with session_factory() as session:
        if isinstance(payload, WatchStatusState):
            disposition = await apply_watch_status(session, payload)
        else:
            disposition = "ignored_event_type"
        await advance_cursor(session, WATCH_STATUS_TOPIC, message.message_id)
        await session.commit()
    return disposition


async def _persist_skip(session_factory: async_sessionmaker[AsyncSession], message_id: str) -> None:
    """Durably record that a message was skipped, so a restart does not re-hit it.

    Never raises: if the cursor write fails the in-memory advance still holds,
    and a restart re-reads and re-skips the frame — noisy, not wedged.
    """
    try:
        async with session_factory() as session:
            await advance_cursor(session, WATCH_STATUS_TOPIC, message_id)
            await session.commit()
    except Exception:
        logger.exception(
            "Failed to persist skip; restart will re-process the frame",
            extra={"message_id": message_id},
        )


async def _skip_poison(
    session_factory: async_sessionmaker[AsyncSession],
    reader: AsyncBusTailReader,
    exc: BusMessageAnomaly,
) -> None:
    """Advance past a frame that will not decode — in memory and durably.

    This log line is the only record the frame leaves behind (no DLQ on this
    stream kind); the LWW republish is the repair for whatever state it carried.

    ``seek`` happens **after** the sentinel guard, not before: ``"?"`` is
    ``from_wire``'s placeholder when no id was supplied, and seeking the cursor
    to it would leave every subsequent ``xread`` raising on an invalid stream
    id — a permanent wedge, strictly worse than not handling the case at all
    (CR round 1, finding 2).
    """
    message_id = getattr(exc, "message_id", None) or "?"
    logger.error(
        "Skipping undecodable frame on info.watch-status",
        extra={"message_id": message_id, "error": error_text(exc)},
        exc_info=exc,
    )
    if message_id == "?":
        return
    reader.seek(message_id)
    await _persist_skip(session_factory, message_id)


async def _skip_unappliable(
    session_factory: async_sessionmaker[AsyncSession],
    message: BusMessage,
    exc: Exception,
) -> None:
    """Advance past a decoded message the registry can never write.

    The reader's in-memory cursor already moved past it during ``read``; only
    the durable cursor needs catching up. Logged at ERROR because this drops
    state the producer sent, and the next republish is what restores it.
    """
    logger.error(
        "Skipping unappliable watch-status message",
        extra={"message_id": message.message_id, "error": error_text(exc)},
        exc_info=exc,
    )
    await _persist_skip(session_factory, message.message_id)


async def consume_once(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    reader: AsyncBusTailReader,
    block_ms: int | None = None,
) -> int:
    """Read and apply up to ``READ_COUNT`` messages. Returns how many applied.

    Three dispositions, and the middle one is the reason this is not a plain
    try/except:

    - **Decode failure** — settled inside (logged + skipped), returns 0 so the
      loop keeps its cadence.
    - **Un-appliable** (``_UNAPPLIABLE_DB_ERRORS``) — logged and skipped past.
      Redelivery reproduces it exactly, so retrying is an infinite stall.
    - **Anything else** (the database being down, a bug of ours) — rewinds the
      reader to the pre-read cursor and re-raises, so the loop backs off and
      the next iteration redelivers. The entry is never lost to an in-memory
      cursor that outran the persisted one.
    """
    resume_point = reader.cursor
    try:
        messages = await reader.read(count=READ_COUNT, block_ms=block_ms)
    except BusMessageAnomaly as exc:
        await _skip_poison(session_factory, reader, exc)
        return 0

    applied = 0
    for message in messages:
        try:
            disposition = await handle_message(session_factory, message)
        except _UNAPPLIABLE_DB_ERRORS as exc:
            await _skip_unappliable(session_factory, message, exc)
            continue
        except Exception:
            reader.seek(resume_point)
            raise
        logger.info(
            "Applied watch-status message",
            extra={"message_id": message.message_id, "disposition": disposition},
        )
        applied += 1
    return applied


async def run(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    reader: AsyncBusTailReader,
    stop_event: asyncio.Event | None = None,
    block_ms: int = READ_BLOCK_MS,
    error_backoff_base: float = ERROR_BACKOFF_BASE_SECONDS,
) -> None:
    """Loop until ``stop_event`` is set, tailing scheduler status.

    The blocking read paces the loop; only a failing iteration backs off
    (escalating, capped, logged every ``ERROR_LOG_EVERY``-th so a sustained
    broker outage cannot flood the journal). ``asyncio.CancelledError``
    propagates for shutdown; everything else is logged and the loop continues.
    """
    stop_event = stop_event or asyncio.Event()
    logger.info(
        "info.watch-status tail starting",
        extra={"topic": WATCH_STATUS_TOPIC, "start_id": reader.cursor},
    )

    consecutive_failures = 0
    while not stop_event.is_set():
        try:
            await consume_once(session_factory=session_factory, reader=reader, block_ms=block_ms)
            if consecutive_failures:
                logger.warning(
                    "info.watch-status tail recovered",
                    extra={"after_failures": consecutive_failures},
                )
            consecutive_failures = 0
            continue
        except asyncio.CancelledError:
            raise
        except Exception:
            consecutive_failures += 1
            if consecutive_failures == 1 or consecutive_failures % ERROR_LOG_EVERY == 0:
                logger.exception(
                    "info.watch-status tail loop error; backing off",
                    extra={"consecutive_failures": consecutive_failures},
                )

        delay = error_backoff_seconds(consecutive_failures, error_backoff_base)
        await asyncio.wait(
            [asyncio.create_task(stop_event.wait())],
            timeout=delay,
            return_when=asyncio.FIRST_COMPLETED,
        )
