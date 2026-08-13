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

**No DLQ, matching ``content.fetch-policy``.** A frame that will not decode is
logged and skipped — with no group there is no PEL to quarantine from, and on
an LWW stream the producer's periodic republish is the repair. The skip is
persisted too, so a restart does not re-hit the poison frame forever.

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


async def _skip_poison(
    session_factory: async_sessionmaker[AsyncSession],
    reader: AsyncBusTailReader,
    exc: BusMessageAnomaly,
) -> None:
    """Advance past a frame that will not decode — in memory and durably.

    This log line is the only record the frame leaves behind (no DLQ on this
    stream kind); the LWW republish is the repair for whatever state it
    carried. If persisting the skip fails the in-memory seek still holds, and
    a restart re-hits the frame and logs it again — noisy, not wedged.
    """
    message_id = getattr(exc, "message_id", None) or "?"
    logger.error(
        "Skipping undecodable frame on info.watch-status",
        extra={"message_id": message_id, "error": error_text(exc)},
        exc_info=exc,
    )
    reader.seek(message_id)
    if message_id == "?":
        return
    try:
        async with session_factory() as session:
            await advance_cursor(session, WATCH_STATUS_TOPIC, message_id)
            await session.commit()
    except Exception:
        logger.exception(
            "Failed to persist skip of undecodable frame; restart will re-log it",
            extra={"message_id": message_id},
        )


async def consume_once(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    reader: AsyncBusTailReader,
    block_ms: int | None = None,
) -> int:
    """Read and apply up to ``READ_COUNT`` messages. Returns how many applied.

    A decode failure is settled inside (logged + skipped), returning 0 so the
    loop keeps its cadence. An apply failure (the database being down) rewinds
    the reader to the pre-read cursor and re-raises, so the loop backs off and
    the next iteration redelivers — the entry is never lost to an in-memory
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
        except Exception:
            reader.seek(resume_point)
            raise
        logger.info(
            "watch-status message %s",
            disposition,
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
