"""Producer-side outbox observability (archiver#112).

Three numbers, computed on request - never cached, never per-tick:

- ``unpublished_count`` / ``oldest_unpublished_age_seconds`` over the drain
  loop's exact live predicate (``published_at IS NULL AND dead_lettered_at IS
  NULL``), served by the ``ix_changes_outbox_unpublished_created`` partial
  index. Age deliberately excludes dead-lettered rows: a retired poison row is
  terminal, and counting it would make a handled incident look like a wedged
  backlog forever.
- ``dead_lettered_count`` over the terminal rows archiver#107 introduced,
  served by the ``ix_changes_outbox_dead_lettered`` partial index. Nonzero is
  an operator signal: the one-time ERROR at dead-letter time is otherwise the
  only trace (the archiver#109 activation found 5 poison rows only because
  someone happened to be tailing the journal).

Consumers: the dashboard health badge (``/dashboard/health/outbox``) and the
publisher drain loop's periodic ``log_outbox_stats`` line.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.logging import get_logger
from src.core.models import ChangesOutboxRow

logger = get_logger(__name__)

# Oldest-live-row age past which the backlog is abnormal. The drain publishes
# batches of 100 at a sub-second cadence, so a healthy row is published within
# seconds; minutes-old means the publisher is down, wedged, or Redis has been
# unreachable for a while (transient retries are deliberately indefinite).
BACKLOG_WARN_AGE_SECONDS = 300.0

_LIVE = (
    ChangesOutboxRow.published_at.is_(None),
    ChangesOutboxRow.dead_lettered_at.is_(None),
)


@dataclass(frozen=True)
class OutboxStats:
    """Point-in-time producer-side health of ``changes_outbox``."""

    unpublished_count: int
    oldest_unpublished_age_seconds: float | None
    dead_lettered_count: int


async def collect_outbox_stats(
    session: AsyncSession, *, now: datetime | None = None
) -> OutboxStats:
    """Compute the three stats with indexed queries; ``now`` overrides the clock
    for tests. Age is clamped to zero so app/DB clock skew cannot go negative."""
    unpublished_count = (
        await session.execute(select(func.count()).select_from(ChangesOutboxRow).where(*_LIVE))
    ).scalar_one()
    oldest_created_at = (
        await session.execute(select(func.min(ChangesOutboxRow.created_at)).where(*_LIVE))
    ).scalar_one()
    dead_lettered_count = (
        await session.execute(
            select(func.count())
            .select_from(ChangesOutboxRow)
            .where(ChangesOutboxRow.dead_lettered_at.is_not(None))
        )
    ).scalar_one()

    oldest_age: float | None = None
    if oldest_created_at is not None:
        reference = now if now is not None else datetime.now(UTC)
        oldest_age = max(0.0, (reference - oldest_created_at).total_seconds())

    return OutboxStats(
        unpublished_count=unpublished_count,
        oldest_unpublished_age_seconds=oldest_age,
        dead_lettered_count=dead_lettered_count,
    )


async def log_outbox_stats(session_factory: async_sessionmaker[AsyncSession]) -> None:
    """Emit one structured stats line; the publisher loop calls this on a timer.

    INFO when healthy, WARNING while any dead-lettered row exists (persistent
    visibility at the same filter level as the publish-failure logs). Pure
    observability: any failure is logged and swallowed so it can never take
    down the drain loop it rides in.
    """
    try:
        async with session_factory() as session:
            stats = await collect_outbox_stats(session)
    except Exception:
        logger.warning("Outbox stats collection failed", exc_info=True)
        return

    emit = logger.warning if stats.dead_lettered_count else logger.info
    emit(
        "Outbox stats",
        extra={
            "unpublished_count": stats.unpublished_count,
            "oldest_unpublished_age_seconds": stats.oldest_unpublished_age_seconds,
            "dead_lettered_count": stats.dead_lettered_count,
        },
    )
