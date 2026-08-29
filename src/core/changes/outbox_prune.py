"""Retention pass over published ``changes_outbox`` rows (archiver#189).

The outbox is the producer-side delivery guarantee. Once a row is published that
guarantee is discharged and the row's only residual value is forensic - the
``bus_message_id`` correlating it to a stream entry - so it is prunable. Nothing
in the service reads a published row: the drain selects on the live predicate,
the #112 stats count live and dead-lettered rows only, and
``info_items.announced_at`` exists precisely so the drift detector's clock does
not live on ``published_at`` (archiver#151, written down against this day).

Two states are never prunable:

- **Live** (``published_at IS NULL AND dead_lettered_at IS NULL``) - the drain's
  own queue. Age is irrelevant; an ancient live row is the backlog the #112
  stats exist to surface, not garbage.
- **Dead-lettered** - the archiver#107 post-mortem record and the #112 danger
  signal. The publisher only ever dead-letters an *unpublished* row, so
  ``published_at IS NOT NULL`` already excludes them; the clause is stated
  anyway so the exclusion is a property of this query rather than an emergent
  consequence of another module.

**Where this runs.** Inside ``publisher.run``, on its own cadence, alongside the
periodic XTRIM and the stats line - not on a systemd timer. A timer would need
``ARCHIVER_ALLOW_PRODUCTION_DB``, and a third sanctioned holder of a
write-capable production-DB opt-in is a real cost to weigh against deleting
delivered rows. Riding the drain loop has no coverage hole either: a published
row can only exist if the publisher ran, so a bus-dormant deployment has
nothing to prune.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.logging import get_logger
from src.core.models import ChangesOutboxRow

logger = get_logger(__name__)

# Default retention when ARCHIVER_OUTBOX_RETENTION_DAYS is unset. Sized against
# what a published row is still good for: correlating a bus_message_id back to
# an entry on info.changes, which is itself capped at DEFAULT_STREAM_MAXLEN.
# 30 days comfortably outlives any incident window and is far short of the point
# where the correlation target is reliably still on the stream.
DEFAULT_RETENTION_DAYS = 30

# One prune deletes at most batch_size * max_batches rows, in batch_size chunks
# committed separately. Two reasons for the bound: the first prune against a
# table that has been growing since before the pruner existed is the only risky
# one (a single unbounded DELETE there is a long lock and a bloat spike), and a
# capped pass keeps this housekeeping's worst case off the drain's cadence.
# The ceiling still dwarfs any plausible accrual between ticks - at hourly
# cadence it clears ~240k rows/day against a service producing tens.
DEFAULT_PRUNE_BATCH_SIZE = 1_000
MAX_PRUNE_BATCHES = 10


def resolve_retention_days(raw: str | None) -> int | None:
    """Parse the ``ARCHIVER_OUTBOX_RETENTION_DAYS`` knob into a retention window.

    Returns the positive day count, or ``None`` to disable pruning (a ``<= 0``
    value). Unset falls back to ``DEFAULT_RETENTION_DAYS`` (pruning on by
    default). Same contract as ``publisher.resolve_stream_maxlen``, for the same
    reason: a **malformed** value falls back and warns rather than raising,
    because ``main.lifespan`` resolves it inside the broad guard that would
    otherwise disable the entire publisher over a retention typo.
    """
    if raw is None:
        return DEFAULT_RETENTION_DAYS
    try:
        value = int(raw)
    except ValueError:
        logger.warning(
            "Invalid ARCHIVER_OUTBOX_RETENTION_DAYS; falling back to default",
            extra={"value": raw, "default": DEFAULT_RETENTION_DAYS},
        )
        return DEFAULT_RETENTION_DAYS
    return value if value > 0 else None


async def prune_published_rows(
    session: AsyncSession,
    *,
    retention_days: int,
    now: datetime | None = None,
    batch_size: int = DEFAULT_PRUNE_BATCH_SIZE,
    max_batches: int = MAX_PRUNE_BATCHES,
) -> int:
    """Delete published rows older than the window; return how many went.

    Batched and capped (see the constants). Each batch commits on its own, so a
    long first prune is a sequence of short transactions rather than one held
    lock. A short batch means the queue is drained and the loop stops early.
    ``now`` overrides the clock for tests.

    The ``id IN (SELECT ... LIMIT n)`` shape is what makes the batch bounded;
    the inner select rides ``ix_changes_outbox_published``, the partial index
    over ``published_at IS NOT NULL`` added with this pruner. Without it the
    prune degrades to a seq scan of exactly the rows it exists to bound.
    """
    reference = now if now is not None else datetime.now(UTC)
    cutoff = reference - timedelta(days=retention_days)
    deleted = 0
    for _ in range(max_batches):
        doomed = (
            select(ChangesOutboxRow.id)
            .where(
                ChangesOutboxRow.published_at.is_not(None),
                ChangesOutboxRow.published_at < cutoff,
                ChangesOutboxRow.dead_lettered_at.is_(None),
            )
            .order_by(ChangesOutboxRow.published_at)
            .limit(batch_size)
        )
        result = await session.execute(
            delete(ChangesOutboxRow)
            .where(ChangesOutboxRow.id.in_(doomed))
            .execution_options(synchronize_session=False)
        )
        await session.commit()
        deleted += result.rowcount
        if result.rowcount < batch_size:
            break
    return deleted


async def prune_outbox(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    retention_days: int | None,
    now: datetime | None = None,
) -> None:
    """Run one retention pass; the publisher loop calls this on a timer.

    ``retention_days=None`` disables the pass entirely. Logs once per pass that
    actually deleted something - the healthy steady state is nothing to prune,
    and a line every tick for zero rows is noise that would bury the one that
    matters. Pure housekeeping: any failure is logged and swallowed so it can
    never take down the drain loop it rides in.
    """
    if retention_days is None:
        return
    try:
        async with session_factory() as session:
            deleted = await prune_published_rows(session, retention_days=retention_days, now=now)
    except Exception:
        logger.warning("Outbox prune failed", exc_info=True)
        return

    if deleted:
        logger.info(
            "Outbox pruned",
            extra={
                "deleted": deleted,
                "retention_days": retention_days,
                # A pass that hit its ceiling has more to do; the next tick picks
                # it up. Visible so a persistently capped prune (a backlog the
                # cadence cannot outrun) is diagnosable from journald alone.
                "capped": deleted >= DEFAULT_PRUNE_BATCH_SIZE * MAX_PRUNE_BATCHES,
            },
        )
