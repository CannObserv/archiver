"""Outbox-to-Redis-Stream publisher background task.

Drains pending rows from ``information.changes_outbox`` and XADDs each to its
declared topic on Redis. Best-effort retry: failed publishes increment
``publish_attempts`` and record ``last_error``; the row stays unpublished and
is re-attempted on the next loop iteration.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.logging import get_logger
from src.core.models import ChangesOutboxRow

logger = get_logger(__name__)

DEFAULT_BATCH_SIZE = 100
ACTIVE_INTERVAL_SECONDS = 0.25
IDLE_INTERVAL_SECONDS = 1.0


class RedisLike(Protocol):
    """Subset of redis.asyncio API the publisher uses."""

    async def xadd(self, name: str, fields: dict, *args, **kwargs) -> bytes | str: ...


async def drain_once(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    redis: RedisLike,
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
                fields = {
                    "key": row.payload.get("source_revision_id", "")
                    if isinstance(row.payload, dict)
                    else "",
                    "payload": json.dumps(row.payload),
                }
                msg_id = await redis.xadd(row.topic, fields)
                if isinstance(msg_id, bytes):
                    msg_id = msg_id.decode()
                row.published_at = datetime.now(UTC)
                row.bus_message_id = msg_id
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
    redis: RedisLike,
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
                redis=redis,
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
