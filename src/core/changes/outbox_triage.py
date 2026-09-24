"""Triage for dead-lettered ``changes_outbox`` rows (archiver#191).

The publisher dead-letters a row it cannot publish (archiver#107), and until
this module nothing cleared ``dead_lettered_at``: the #112 warning could not be
acknowledged, and an operator-fixed row could not be republished. #189's pruner
exempts the set by design, so these operations are its only exit.

Two operations, **both by explicit row id**, never a predicate - "retire
everything dead-lettered" is how a real backlog is silently discarded:

- **Discard** deletes the row. Each is logged in full first, because the ERROR
  line written at dead-letter time outlives neither journald's retention (about
  two weeks on this host) nor a slow triage.
- **Rearm** clears ``dead_lettered_at`` and ``publish_attempts`` so the drain
  selects the row again. It is guarded twice. The pure build phase runs first,
  so build-phase poison - deterministic, and re-dead-lettered on the next drain
  - is ``rejected`` rather than looped; a row that now builds is the co-core
  version-skew case, the analogue of the DLQ's ``decodes`` (archiver#238). And
  only ``REARMABLE_TOPICS`` rearm at all.

**No auto-expiry.** An untriaged incident record ageing out silently is worse
than a permanent warning, so a dead-lettered row leaves only through here.

These write the database, not the broker, so the dev server exercises them
against its own. On production they are an operator's decision about named rows.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from co_core.pure.adapters.bus.envelope import payload_from_dict, to_wire
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.core.changes.diagnostics import error_text
from src.core.changes.publisher import CHANGE_STREAM_TOPIC
from src.core.logging import get_logger
from src.core.models import ChangesOutboxRow

logger = get_logger(__name__)

REARMABLE_TOPICS: frozenset[str] = frozenset({CHANGE_STREAM_TOPIC})
"""Topics whose dead-lettered rows may go back to the drain.

``info.changes`` is a fact stream whose consumers dedupe on the envelope key, so
a late publish is just late. The other two are refused:

- ``info.registry`` - per-item last-write-wins state. The hourly full-set
  snapshot republishes current state, and a stale delta loses on generation
  anyway. The repair already happened; discard the row.
- ``content.replicate`` - a command. The reaper abandons one after its horizon
  and never re-issues, because a second artifact in a permanent store has no way
  back. A rearmed row could publish a command whose ``replication_commands`` row
  is already closed. Re-replicating is the manual action's (archiver#171), which
  mints a fresh ``command_id``.
"""

RearmOutcome = Literal["rearmed", "not_found", "refused", "rejected"]


@dataclass(frozen=True, slots=True)
class DiscardOutcome:
    """What a discard did, each list in request order."""

    discarded: list[str]
    not_found: list[str]


@dataclass(frozen=True, slots=True)
class RearmResult:
    """What happened to one requested row. Only ``rearmed`` changed it."""

    row_id: str
    outcome: RearmOutcome
    detail: str | None = None


def _distinct(row_ids: Iterable[str]) -> list[str]:
    """``row_ids`` without repeats, first occurrence kept."""
    return list(dict.fromkeys(row_ids))


async def _locked_dead_lettered(
    session: AsyncSession, row_ids: list[str]
) -> dict[str, ChangesOutboxRow]:
    """The named rows that are dead-lettered, locked, keyed by their id string.

    The ``dead_lettered_at IS NOT NULL`` clause is the whole guard: a live or
    published row is never returned, so neither operation can touch one.
    """
    result = await session.execute(
        select(ChangesOutboxRow)
        .where(
            ChangesOutboxRow.id.in_([ULID.from_str(r) for r in row_ids]),
            ChangesOutboxRow.dead_lettered_at.is_not(None),
        )
        .with_for_update()
    )
    return {str(row.id): row for row in result.scalars()}


def _row_record(row: ChangesOutboxRow) -> dict[str, object]:
    """The row as a journald record: everything a post-mortem could want."""
    return {
        "row_id": str(row.id),
        "topic": row.topic,
        "payload": row.payload,
        "last_error": row.last_error,
        "publish_attempts": row.publish_attempts,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "dead_lettered_at": row.dead_lettered_at.isoformat() if row.dead_lettered_at else None,
    }


async def list_dead_lettered(
    session: AsyncSession, *, limit: int, offset: int
) -> tuple[list[ChangesOutboxRow], bool]:
    """A page of dead-lettered rows, oldest dead-lettering first, and ``has_more``.

    Rides ``ix_changes_outbox_dead_lettered``, the partial index over exactly
    this set.
    """
    result = await session.execute(
        select(ChangesOutboxRow)
        .where(ChangesOutboxRow.dead_lettered_at.is_not(None))
        .order_by(ChangesOutboxRow.dead_lettered_at, ChangesOutboxRow.id)
        .limit(limit + 1)
        .offset(offset)
    )
    rows = list(result.scalars())
    return rows[:limit], len(rows) > limit


async def discard_dead_lettered(session: AsyncSession, row_ids: Iterable[str]) -> DiscardOutcome:
    """Delete the named dead-lettered rows, each logged in full first; commit.

    One transaction: a failure rolls every delete back, so there is no partial
    outcome to report, and it is logged so the per-row lines are not read as
    done. An id that is unknown, live or published comes back in
    ``not_found``, which also makes a retried discard harmless.
    """
    requested = _distinct(row_ids)
    found = await _locked_dead_lettered(session, requested)
    discarded = [r for r in requested if r in found]
    for row_id in discarded:
        logger.info("Discarding dead-lettered outbox row", extra=_row_record(found[row_id]))
    try:
        if discarded:
            await session.execute(
                delete(ChangesOutboxRow)
                .where(ChangesOutboxRow.id.in_([found[r].id for r in discarded]))
                .execution_options(synchronize_session=False)
            )
        await session.commit()
    except Exception:
        # The lines above were written before the delete, so without this one
        # journald would record a discard that never happened.
        logger.warning(
            "Discard of dead-lettered outbox rows rolled back",
            extra={"row_ids": discarded},
            exc_info=True,
        )
        raise
    return DiscardOutcome(discarded=discarded, not_found=[r for r in requested if r not in found])


def _build_error(row: ChangesOutboxRow) -> str | None:
    """Why the drain's build phase would still refuse ``row``; ``None`` if it builds.

    The same pure call ``drain_once`` makes, so a pass here is a pass there.
    """
    try:
        to_wire(payload_from_dict(row.payload))
    except Exception as exc:
        return error_text(exc)[:1000]
    return None


def _decide(row: ChangesOutboxRow | None, row_id: str) -> RearmResult:
    """The outcome for one row, before anything is written."""
    if row is None:
        return RearmResult(row_id, "not_found")
    if row.topic not in REARMABLE_TOPICS:
        return RearmResult(
            row_id,
            "refused",
            f"{row.topic} rows are not rearmable; discard it (see REARMABLE_TOPICS)",
        )
    error = _build_error(row)
    if error is not None:
        return RearmResult(row_id, "rejected", error)
    return RearmResult(row_id, "rearmed")


async def rearm_dead_lettered(session: AsyncSession, row_ids: Iterable[str]) -> list[RearmResult]:
    """Return the named dead-lettered rows to the drain's queue; commit.

    Clears ``dead_lettered_at`` and resets ``publish_attempts``, so the attempt
    ceiling gives a rearmed row its full headroom. ``last_error`` stays until a
    publish replaces or clears it. One result per distinct id, in request order.
    """
    requested = _distinct(row_ids)
    found = await _locked_dead_lettered(session, requested)
    results = [_decide(found.get(r), r) for r in requested]
    for result in results:
        if result.outcome != "rearmed":
            continue
        row = found[result.row_id]
        logger.info("Re-arming dead-lettered outbox row", extra=_row_record(row))
        row.dead_lettered_at = None
        row.publish_attempts = 0
    await session.commit()
    return results
