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
delivered rows.

**What that siting does and does not cover.** A published row can only exist if
the drain has run, so a deployment that has never had ``ARCHIVER_REDIS_URL`` set
accrues nothing to prune. It does *not* follow that retention is unconditional:
pruning needs the drain running **now**. Unsetting ``ARCHIVER_REDIS_URL`` on an
instance that has been live freezes retention with whatever published backlog
already exists - the table stops growing and stops shrinking, and nothing reports
that. Bus-dormant is a local-dev mode, so the residual case is narrow, but it is
a real one and not a hole this siting closes.
"""

from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(frozen=True)
class PruneOutcome:
    """What one retention pass did.

    ``capped`` means the pass exhausted its batch ceiling with every batch full,
    so rows past the window remain and the next tick picks them up. It is derived
    from the loop that actually ran, never recomputed from the module constants -
    a caller passing its own bounds gets a flag about *its* pass.
    """

    deleted: int
    capped: bool


class OutboxPruneError(Exception):
    """A pass that failed partway, carrying what it had already committed.

    Batches commit as they go, so a mid-pass failure leaves rows genuinely
    deleted. Without this the count dies with the exception and journald
    under-reports the one pass an operator most wants an accurate account of.

    Deliberately carries the count alone rather than a ``PruneOutcome``: an
    interrupted pass never learned whether it would have capped, and a flag
    invented on the error path is a wrong value waiting for its first reader.
    """

    def __init__(self, *, deleted: int) -> None:
        super().__init__(f"outbox prune failed after {deleted} rows")
        self.deleted = deleted


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


async def prune_batch(session: AsyncSession, *, cutoff: datetime, batch_size: int) -> int:
    """Delete one bounded batch of published rows past ``cutoff``; commit it.

    The ``id IN (SELECT ... LIMIT n)`` shape is what makes the batch bounded; the
    inner select rides ``ix_changes_outbox_published``, the partial index over
    ``published_at IS NOT NULL`` added with this pruner. Without it the prune
    degrades to a seq scan of exactly the rows it exists to bound.

    ``dead_lettered_at IS NULL`` is redundant against a publisher that only ever
    dead-letters an unpublished row. It is stated anyway so the archiver#107
    exemption is a property of this query rather than an emergent consequence of
    another module.
    """
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
    return result.rowcount


async def prune_published_rows(
    session: AsyncSession,
    *,
    retention_days: int,
    now: datetime | None = None,
    batch_size: int = DEFAULT_PRUNE_BATCH_SIZE,
    max_batches: int = MAX_PRUNE_BATCHES,
) -> PruneOutcome:
    """Delete published rows older than the window; report what went.

    Batched and capped (see the constants). Each batch commits on its own, so a
    long first prune is a sequence of short transactions rather than one held
    lock. A short batch means the queue is drained and the loop stops early.
    ``now`` overrides the clock for tests.

    The window boundary is a strict ``<``: a row published exactly at the cutoff
    survives this pass and goes on the next one.

    Raises ``OutboxPruneError`` carrying the rows already committed when a batch
    fails - they are gone either way, so the count has to outlive the error.
    """
    reference = now if now is not None else datetime.now(UTC)
    cutoff = reference - timedelta(days=retention_days)
    deleted = 0
    full_batches = 0
    for _ in range(max_batches):
        try:
            rowcount = await prune_batch(session, cutoff=cutoff, batch_size=batch_size)
        except Exception as e:
            raise OutboxPruneError(deleted=deleted) from e
        deleted += rowcount
        if rowcount < batch_size:
            break
        full_batches += 1
    # Capped means the budget ran out with rows still to go. The ``max_batches``
    # guard keeps a pass that was never given a batch to run from claiming a
    # ceiling it never reached - it stopped for lack of budget, but it also never
    # learned whether anything was left.
    capped = max_batches > 0 and full_batches == max_batches
    return PruneOutcome(deleted=deleted, capped=capped)


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
    never take down the drain loop it rides in, and the warning carries the rows
    the failed pass had already committed.
    """
    if retention_days is None:
        return
    try:
        async with session_factory() as session:
            outcome = await prune_published_rows(session, retention_days=retention_days, now=now)
    except OutboxPruneError as e:
        logger.warning("Outbox prune failed", extra={"deleted": e.deleted}, exc_info=True)
        return
    except Exception:
        # Never reached the first batch (the session itself failed to open, or
        # the clock/knob math raised): nothing was deleted, and saying so beats
        # an absent count that reads as unknown.
        logger.warning("Outbox prune failed", extra={"deleted": 0}, exc_info=True)
        return

    if outcome.deleted:
        logger.info(
            "Outbox pruned",
            extra={
                "deleted": outcome.deleted,
                "retention_days": retention_days,
                # A pass that hit its ceiling has more to do; the next tick picks
                # it up. Visible so a persistently capped prune (a backlog the
                # cadence cannot outrun) is diagnosable from journald alone.
                "capped": outcome.capped,
            },
        )
