"""Apply one ``info.watch-status`` message to local state (archiver#151).

The write half of the tail consumer: last-write-wins upsert of the
``watch_status`` cache in stream order, tombstone purge, the durable
``info_sources.last_observed_at`` write-through, and the per-stream resume
cursor. Everything here is observability — a failure degrades the panel and
must never block a registry write, so the consumer calls in with its own
session and its own transaction.

**The write-through's two guards.** ``WatchStatusState`` is keyed by
``info_item_id`` but the durable column lives on ``info_sources``, so the stamp
resolves through the item's *active* binding — which opens a rebind race: the
producer coalesces publishes, so a message up to a republish period old can
arrive after the item was rebound and would stamp the *new* source as
observed. That is the one direction the design forbids (claiming freshness
that is not real). Hence:

- **Monotonic** — ``last_observed_at`` never moves backwards.
- **Binding-age** — no stamp when the active binding postdates the observation;
  an observation older than the binding says nothing about *this* source.

The cache row itself always records the reported value verbatim; the guards
protect only the durable registry column.
"""

from datetime import UTC, datetime
from typing import Literal

from co_core.pure.adapters.bus.streams import INFO_WATCH_STATUS
from co_core.pure.models.changes import WatchStatusState
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.core.logging import get_logger
from src.core.models import BusTailCursor, InfoItem, InfoItemSource, InfoSource, WatchStatus

logger = get_logger(__name__)

WATCH_STATUS_TOPIC = INFO_WATCH_STATUS

Disposition = Literal["applied", "revoked", "unknown_item", "invalid_id"]


def _parse_item_id(raw: str) -> ULID | None:
    try:
        return ULID.from_str(raw)
    except (ValueError, TypeError):
        return None


async def _stamp_source_observed(
    session: AsyncSession, info_item_id: ULID, observed_at: datetime
) -> None:
    """Write ``last_observed_at`` through to the active primary source, guarded."""
    binding = (
        await session.execute(
            select(InfoItemSource).where(
                InfoItemSource.info_item_id == info_item_id,
                InfoItemSource.deactivated_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if binding is None:
        return
    if binding.created_at is not None and binding.created_at > observed_at:
        # The observation predates the binding — it was of some earlier source.
        return
    await session.execute(
        update(InfoSource)
        .where(
            InfoSource.info_source_id == binding.info_source_id,
            (InfoSource.last_observed_at.is_(None)) | (InfoSource.last_observed_at < observed_at),
        )
        .values(last_observed_at=observed_at)
    )


async def apply_watch_status(session: AsyncSession, state: WatchStatusState) -> Disposition:
    """Apply one status message. Caller commits; LWW in stream order.

    Dispositions: ``applied`` (upserted), ``revoked`` (cache row deleted —
    idempotent, a republished tombstone is a no-op), ``unknown_item`` (the
    registry is the authority on what exists; a status for something it does
    not hold is dropped), ``invalid_id`` (undecodable key — dropped, since
    redelivery yields the identical value).
    """
    item_id = _parse_item_id(state.info_item_id)
    if item_id is None:
        return "invalid_id"

    if state.revoked:
        await session.execute(delete(WatchStatus).where(WatchStatus.info_item_id == item_id))
        return "revoked"

    exists = (
        await session.execute(select(InfoItem.info_item_id).where(InfoItem.info_item_id == item_id))
    ).scalar_one_or_none()
    if exists is None:
        return "unknown_item"

    values = {
        "applied_generation": state.applied_generation,
        "applied_active": state.applied_active,
        "applied_interval": state.applied_interval,
        "last_attempt_at": state.last_attempt_at,
        "last_observed_at": state.last_observed_at,
        "health": state.health,
        "occurred_at": state.occurred_at,
        "updated_at": datetime.now(UTC),
    }
    stmt = pg_insert(WatchStatus).values(info_item_id=item_id, **values)
    await session.execute(
        stmt.on_conflict_do_update(index_elements=[WatchStatus.info_item_id], set_=values)
    )

    if state.last_observed_at is not None:
        await _stamp_source_observed(session, item_id, state.last_observed_at)
    return "applied"


async def read_cursor(session: AsyncSession, stream: str) -> str | None:
    """The last stream id applied, or ``None`` for a cold start (replay 0-0)."""
    return (
        await session.execute(select(BusTailCursor.last_id).where(BusTailCursor.stream == stream))
    ).scalar_one_or_none()


async def advance_cursor(session: AsyncSession, stream: str, last_id: str) -> None:
    """Persist the resume point — same transaction as the write it covers.

    Atomic with the apply: a crash between the two is impossible, and a restart
    re-applies an idempotent LWW upsert rather than losing or doubling state.
    """
    now = datetime.now(UTC)
    stmt = pg_insert(BusTailCursor).values(stream=stream, last_id=last_id, updated_at=now)
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=[BusTailCursor.stream], set_={"last_id": last_id, "updated_at": now}
        )
    )
