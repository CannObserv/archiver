"""Outbox-to-Redis-Stream publisher background task.

Drains pending rows from ``information.changes_outbox`` and publishes each to its
declared topic on Redis via the shared co-core bus driver
(``co_core_aio.bus.AsyncBusPublisher`` executing a ``BusPublish`` effect). The
wire envelope is built by the pure ``co_core.pure.adapters.bus.envelope.to_wire``
serializer — archiver no longer hand-rolls the XADD field map (archiver#106).
The transactional outbox stays here (the producer-side delivery guarantee);
co-core provides only the publish effect/driver the drain loop calls.

Best-effort retry: failed publishes increment ``publish_attempts`` and record
``last_error``; the row stays unpublished and is re-attempted on the next loop
iteration.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from co_core.effects.bus import BusPublish
from co_core.pure.adapters.bus.envelope import to_wire
from co_core.pure.models.changes import (
    ChangeEventPayload,
    InfoItemPrimaryChangedEvent,
    SourceRevisionCapturedEvent,
)
from co_core_aio.bus import AsyncBusPublisher
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.logging import get_logger
from src.core.models import ChangesOutboxRow

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = get_logger(__name__)

DEFAULT_BATCH_SIZE = 100
ACTIVE_INTERVAL_SECONDS = 0.25
IDLE_INTERVAL_SECONDS = 1.0

# The single Redis Stream Archiver produces to (both event types share it). Used
# as the operator-side XTRIM target; the emit sites hardcode the same literal.
CHANGE_STREAM_TOPIC = "info.changes"

# Trim the stream every N drain-loop iterations when a cap is configured. With
# the loop's sub-second/idle cadence this bounds growth without an XTRIM every
# tick. Archiver operates the broker (archiver#109), so capping is its job —
# co-core exposes no XADD-time trim arg (BusPublish is topic + fields only).
TRIM_INTERVAL_ITERATIONS = 20

# Default approximate cap on info.changes when ARCHIVER_REDIS_STREAM_MAXLEN is
# unset. See resolve_stream_maxlen for the parse contract.
DEFAULT_STREAM_MAXLEN = 100_000


def resolve_stream_maxlen(raw: str | None) -> int | None:
    """Parse the ``ARCHIVER_REDIS_STREAM_MAXLEN`` knob into a trim cap.

    Returns the positive cap, or ``None`` to disable trimming (a ``<= 0`` value).
    Unset falls back to ``DEFAULT_STREAM_MAXLEN`` (trimming on by default). A
    **malformed** value also falls back to the default and logs a warning — it
    must never raise, because ``main.lifespan`` resolves this inside the broad
    guard that would otherwise disable the entire publisher over a retention
    typo (CR #109).
    """
    if raw is None:
        return DEFAULT_STREAM_MAXLEN
    try:
        value = int(raw)
    except ValueError:
        logger.warning(
            "Invalid ARCHIVER_REDIS_STREAM_MAXLEN; falling back to default",
            extra={"value": raw, "default": DEFAULT_STREAM_MAXLEN},
        )
        return DEFAULT_STREAM_MAXLEN
    return value if value > 0 else None


# event_type -> canonical (consumer-facing, extra="ignore") co-core payload model.
# The outbox stores each event as a JSON dict (``model_dump(mode="json")``); the
# drain loop reconstructs the typed payload so ``to_wire`` can derive the wire
# envelope (incl. the per-type idempotency key) from the single source of truth.
# Archiver produces exactly these two event types on ``info.changes``.
#
# NOTE: this duplicates co-core's private ``envelope._PAYLOAD_BY_EVENT_TYPE`` (a
# 2-of-4 subset) because co-core exposes no public dict->payload constructor —
# ``from_wire`` wants wire fields, not a stored payload dict. Drift risk tracked
# in archiver#108; the upstream public-helper request is cannobserv#264. Delete
# this table and reconstruct via the shared helper once that lands.
_PAYLOAD_BY_EVENT_TYPE: dict[str, type[ChangeEventPayload]] = {
    "source_revision_captured": SourceRevisionCapturedEvent,
    "info_item_primary_changed": InfoItemPrimaryChangedEvent,
}


def _payload_from_row(payload: dict) -> ChangeEventPayload:
    """Reconstruct the typed co-core payload from a stored outbox row dict.

    Raises ``ValueError`` on an unrecognized ``event_type`` so the drain loop
    treats it as a per-row failure (row stays unpublished, error recorded)
    rather than crashing the whole batch.
    """
    event_type = payload.get("event_type") if isinstance(payload, dict) else None
    model = _PAYLOAD_BY_EVENT_TYPE.get(event_type)
    if model is None:
        raise ValueError(f"unknown outbox event_type: {event_type!r}")
    return model.model_validate(payload)


async def drain_once(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    publisher: AsyncBusPublisher,
    batch_size: int = DEFAULT_BATCH_SIZE,
    seen_topics: set[str] | None = None,
) -> int:
    """Drain at most ``batch_size`` unpublished rows.

    Returns number of rows attempted (not necessarily successfully published).

    When ``seen_topics`` is provided, each successfully-published ``row.topic`` is
    added to it, so the caller (``run``) can trim every stream it has actually
    produced to — not just the canonical one — should the topic set ever grow
    beyond ``info.changes``.
    """
    async with session_factory() as session:
        result = await session.execute(
            select(ChangesOutboxRow)
            .where(ChangesOutboxRow.published_at.is_(None))
            .order_by(ChangesOutboxRow.created_at)
            .limit(batch_size)
        )
        rows = list(result.scalars())
        if not rows:
            return 0
        for row in rows:
            try:
                payload = _payload_from_row(row.payload)
                fields = to_wire(payload)
                bus_result = await publisher.execute(BusPublish(topic=row.topic, fields=fields))
                row.published_at = datetime.now(UTC)
                row.bus_message_id = bus_result.bus_message_id
                row.last_error = None
                if seen_topics is not None:
                    seen_topics.add(row.topic)
            # NOTE: a deterministically-failing row (unknown event_type, corrupt
            # payload) has no terminal state — it is re-attempted every loop, not
            # just the transient (Redis-down) case this retry targets. Not
            # reachable via the two current routes; bounded-retry / dead-letter
            # tracked in archiver#107.
            except Exception as exc:
                row.publish_attempts = (row.publish_attempts or 0) + 1
                row.last_error = repr(exc)[:1000]
                logger.warning(
                    "Failed to publish outbox row",
                    extra={
                        "row_id": str(row.id),
                        "topic": row.topic,
                        "error": repr(exc),
                    },
                )
        await session.commit()
        return len(rows)


async def trim_stream(client: Redis, topic: str, maxlen: int) -> None:
    """Cap ``topic`` to roughly ``maxlen`` entries via an approximate ``XTRIM``.

    Operator-side retention (archiver#109): with no consumer yet, entries
    accumulate on ``info.changes``, so Archiver (the broker operator) bounds the
    stream itself. ``approximate=True`` (Redis ``MAXLEN ~``) trims whole
    macro-nodes — cheap, may leave slightly more than ``maxlen``. Best-effort:
    a failing trim is logged and swallowed so it never breaks the drain loop.
    """
    try:
        await client.xtrim(topic, maxlen=maxlen, approximate=True)
    except Exception:
        # exc_info so a *persistent* trim failure (bad type, NOPERM, misconfig)
        # is distinguishable from a transient redis-down blip — the swallow
        # otherwise leaves no trace to diagnose an unbounded stream.
        logger.warning(
            "Stream trim failed",
            extra={"topic": topic, "maxlen": maxlen},
            exc_info=True,
        )


async def run(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    publisher: AsyncBusPublisher,
    batch_size: int = DEFAULT_BATCH_SIZE,
    active_interval: float = ACTIVE_INTERVAL_SECONDS,
    idle_interval: float = IDLE_INTERVAL_SECONDS,
    stop_event: asyncio.Event | None = None,
    redis_client: Redis | None = None,
    stream_maxlen: int | None = None,
    trim_topic: str = CHANGE_STREAM_TOPIC,
    trim_interval_iterations: int = TRIM_INTERVAL_ITERATIONS,
) -> None:
    """Loop forever (until ``stop_event`` is set), draining the outbox.

    Sleeps ``active_interval`` seconds when work was found, ``idle_interval``
    when not.  Handles ``asyncio.CancelledError`` by re-raising; all other
    exceptions are logged and the loop continues.

    When ``redis_client`` and a positive ``stream_maxlen`` are supplied, the loop
    caps every stream it has produced to via ``trim_stream`` every
    ``trim_interval_iterations`` iterations — operator-side retention
    (archiver#109). It trims ``trim_topic`` (the canonical ``info.changes``) until
    a different ``row.topic`` is observed, then trims each observed topic too, so
    an added stream cannot grow unbounded silently. Left unset (the dormant or
    unconfigured case), no trimming occurs.
    """
    stop_event = stop_event or asyncio.Event()
    seen_topics: set[str] = set()
    iteration = 0
    while not stop_event.is_set():
        try:
            count = await drain_once(
                session_factory=session_factory,
                publisher=publisher,
                batch_size=batch_size,
                seen_topics=seen_topics,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Outbox publisher loop hit unexpected error; retrying")
            count = 0

        iteration += 1
        if (
            redis_client is not None
            and stream_maxlen
            and stream_maxlen > 0
            and iteration % trim_interval_iterations == 0
        ):
            # Trim every stream produced to; fall back to the canonical topic so
            # a pre-existing stream is bounded even before the first publish.
            for topic in seen_topics or {trim_topic}:
                await trim_stream(redis_client, topic, stream_maxlen)

        await asyncio.wait(
            [asyncio.create_task(stop_event.wait())],
            timeout=active_interval if count else idle_interval,
            return_when=asyncio.FIRST_COMPLETED,
        )
