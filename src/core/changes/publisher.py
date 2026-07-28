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

logger = get_logger(__name__)

DEFAULT_BATCH_SIZE = 100
ACTIVE_INTERVAL_SECONDS = 0.25
IDLE_INTERVAL_SECONDS = 1.0

# event_type -> canonical (consumer-facing, extra="ignore") co-core payload model.
# The outbox stores each event as a JSON dict (``model_dump(mode="json")``); the
# drain loop reconstructs the typed payload so ``to_wire`` can derive the wire
# envelope (incl. the per-type idempotency key) from the single source of truth.
# Archiver produces exactly these two event types on ``info.changes``.
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
) -> int:
    """Drain at most ``batch_size`` unpublished rows.

    Returns number of rows attempted (not necessarily successfully published).
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


async def run(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    publisher: AsyncBusPublisher,
    batch_size: int = DEFAULT_BATCH_SIZE,
    active_interval: float = ACTIVE_INTERVAL_SECONDS,
    idle_interval: float = IDLE_INTERVAL_SECONDS,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Loop forever (until ``stop_event`` is set), draining the outbox.

    Sleeps ``active_interval`` seconds when work was found, ``idle_interval``
    when not.  Handles ``asyncio.CancelledError`` by re-raising; all other
    exceptions are logged and the loop continues.
    """
    stop_event = stop_event or asyncio.Event()
    while not stop_event.is_set():
        try:
            count = await drain_once(
                session_factory=session_factory,
                publisher=publisher,
                batch_size=batch_size,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Outbox publisher loop hit unexpected error; retrying")
            count = 0
        await asyncio.wait(
            [asyncio.create_task(stop_event.wait())],
            timeout=active_interval if count else idle_interval,
            return_when=asyncio.FIRST_COMPLETED,
        )
