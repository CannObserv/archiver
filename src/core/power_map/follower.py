"""The Power Map org follower (archiver#305): keep every linked org's snapshot current.

``refresh_linked_orgs`` sends one conditional ``GET /orgs/{id}`` (the stored
ETag) per ``pm_organizations`` row an item links, sequentially, and applies the
answer in its own transaction:

| Power Map says | Archiver does |
|---|---|
| 304 | ``checked_at = now`` |
| 200 | ``apply_org_snapshot``; a name/acronym change moves paths, logged per assignment |
| Merged | Upsert the winner, re-point the items, set ``merged_into`` on the loser |
| Gone (404, or 410 without ``merged_into``) | ``missing_since = coalesce(missing_since, now)`` |
| No answer | Nothing; the next run retries |

Every write that changes an item's effective bag takes the InfoItem row locks
first, then the snapshot row - the order ``link_org`` takes them in - so the
follower serializes with assign, save and link (#302). A rename applies without
confirmation (design Q4) but logs the same before → after per assignment that a
confirmed bag save does.

``succeeded_by``, ``archived_at`` and ``active`` are mirrored only: re-linking
to a successor is a human decision.

The timer (``deploy/archiver-pm-org-refresh.timer``) runs ``main`` hourly, and
it exits 0 without touching the database when Power Map is not configured.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import random
import sys
from collections import Counter
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_database_url, get_engine, get_session_factory
from src.core.db_safety import ALLOW_PRODUCTION_DB_ENV, assert_production_db_allowed
from src.core.logging import configure_logging, get_logger
from src.core.models import InfoItem, PmOrganization
from src.core.power_map.client import (
    Merged,
    NotModified,
    OrgResult,
    OrgSnapshot,
    PowerMapUnavailableError,
    Snapshot,
    power_map_from_env,
)
from src.core.power_map.snapshots import OrgUnnamedError, apply_org_snapshot, org_values
from src.core.rep_fields import OrgValues
from src.core.tools.link_org import PowerMapReader
from src.core.tools.set_rep_fields import active_assignments, destination_moves, log_moves

# Literal rather than __name__: the timer runs this module via ``python -m``,
# where __name__ is "__main__" - a useless journald filter key.
logger = get_logger("src.core.power_map.follower")

NOT_MODIFIED = "not_modified"
UPDATED = "updated"
RENAMED = "renamed"
MERGED = "merged"
MISSING = "missing"
UNNAMED = "unnamed"
UNAVAILABLE = "unavailable"

#: Power Map's read bucket is 2 req/s (burst 120): one request per half second
#: never drains it, however many orgs are linked.
PACE_SECONDS = 0.5
#: A 429's ``Retry-After`` up to this long is waited out and the org retried
#: once; longer, and the next hourly run is the retry.
MAX_RETRY_AFTER_SECONDS = 60.0
#: No answer this many orgs in a row means Power Map is down (or rejecting the
#: key), not that one org is bad: stop rather than time out on every org.
MAX_CONSECUTIVE_FAILURES = 3

Sleep = Callable[[float], Awaitable[None]]

#: The sweep order (CR 1). Random rather than oldest-``checked_at``-first: an
#: org with no answer keeps its old ``checked_at``, so a fixed order would put
#: the same failing orgs first every hour and let them end every sweep
#: (``MAX_CONSECUTIVE_FAILURES``) before the rest were ever checked.
_shuffle = random.shuffle


async def refresh_linked_orgs(
    db: AsyncSession,
    power_map: PowerMapReader,
    *,
    pace_seconds: float = PACE_SECONDS,
    sleep: Sleep = asyncio.sleep,
) -> dict[str, str]:
    """Check every linked org once, in random order; returns each checked id's outcome.

    Commits once per org. Power Map is asked outside any transaction, so no
    lock is held across an HTTP round trip.
    """
    rows = list(
        await db.execute(
            select(PmOrganization.pm_org_id, PmOrganization.etag)
            .where(
                PmOrganization.pm_org_id.in_(
                    select(InfoItem.pm_org_id).where(InfoItem.pm_org_id.is_not(None))
                )
            )
            .order_by(PmOrganization.pm_org_id)
        )
    )
    await db.commit()
    _shuffle(rows)

    fetch = _Fetcher(power_map, pace_seconds=pace_seconds, sleep=sleep)
    outcomes: dict[str, str] = {}
    failures = 0
    for pm_org_id, etag in rows:
        outcome = await _refresh_one(db, fetch, pm_org_id, etag)
        outcomes[pm_org_id] = outcome
        failures = failures + 1 if outcome == UNAVAILABLE else 0
        if failures >= MAX_CONSECUTIVE_FAILURES:
            logger.warning(
                "Power Map org refresh stopped: Power Map unavailable",
                extra={"checked": len(outcomes), "linked": len(rows)},
            )
            break
    logger.info(
        "Power Map org refresh finished",
        extra={
            "linked": len(rows),
            "outcomes": dict(Counter(outcomes.values())),
        },
    )
    return outcomes


class _Fetcher:
    """``get_org`` paced for the read bucket, waiting out one short ``Retry-After``."""

    def __init__(self, power_map: PowerMapReader, *, pace_seconds: float, sleep: Sleep) -> None:
        self._power_map = power_map
        self._pace_seconds = pace_seconds
        self._sleep = sleep
        self._sent = False

    async def get_org(self, pm_org_id: str, etag: str | None = None) -> OrgResult:
        try:
            return await self._get(pm_org_id, etag)
        except PowerMapUnavailableError as e:
            if e.retry_after is None or e.retry_after > MAX_RETRY_AFTER_SECONDS:
                raise
            await self._sleep(e.retry_after)
            return await self._get(pm_org_id, etag)

    async def _get(self, pm_org_id: str, etag: str | None) -> OrgResult:
        if self._sent and self._pace_seconds > 0:
            await self._sleep(self._pace_seconds)
        self._sent = True
        return await self._power_map.get_org(pm_org_id, etag)


async def _refresh_one(db: AsyncSession, fetch: _Fetcher, pm_org_id: str, etag: str | None) -> str:
    winner: OrgSnapshot | None = None
    try:
        result = await fetch.get_org(pm_org_id, etag)
        if isinstance(result, Merged):
            # One hop: ``merged_into`` is already the chain's live end (power-map#607).
            answer = await fetch.get_org(result.winner)
            if isinstance(answer, Snapshot):
                winner = answer.org
            else:
                logger.warning(
                    "Power Map merged an org into one it does not have",
                    extra={"pm_org_id": pm_org_id, "winner": result.winner},
                )
    except PowerMapUnavailableError as e:
        logger.warning(
            "Power Map org not refreshed", extra={"pm_org_id": pm_org_id, "reason": e.reason}
        )
        return UNAVAILABLE

    now = datetime.now(UTC)
    try:
        if isinstance(result, NotModified):
            outcome = await _not_modified(db, pm_org_id, now)
        elif isinstance(result, Snapshot):
            outcome = await _snapshot(db, result.org, now)
        elif winner is not None:
            outcome = await _merged(db, pm_org_id, winner, now)
        else:  # Gone, or merged into an org Power Map does not have
            outcome = await _missing(db, pm_org_id, now)
    except OrgUnnamedError as e:
        await db.rollback()
        logger.error(
            "Power Map org has no canonical name; snapshot left as it was",
            extra={"pm_org_id": e.pm_org_id},
        )
        return UNNAMED
    await db.commit()
    return outcome


async def _not_modified(db: AsyncSession, pm_org_id: str, now: datetime) -> str:
    await db.execute(
        update(PmOrganization)
        .where(PmOrganization.pm_org_id == pm_org_id)
        .values(checked_at=now, missing_since=None)
    )
    return NOT_MODIFIED


async def _snapshot(db: AsyncSession, snapshot: OrgSnapshot, now: datetime) -> str:
    items = await _lock_linked_items(db, snapshot.pm_org_id)
    before = org_values(await _lock_org(db, snapshot.pm_org_id))
    after = org_values(await apply_org_snapshot(db, snapshot, now=now))
    if before == after:
        return UPDATED
    await _log_moves(db, items, before, after, "Power Map org rename moved assignment destinations")
    return RENAMED


async def _merged(db: AsyncSession, loser_id: str, winner: OrgSnapshot, now: datetime) -> str:
    """Re-point the loser's items at the winner, then mark the loser.

    Items first: ``info_items.pm_org_id`` is ``RESTRICT``, and the loser row is
    kept for provenance (``merged_into``), never deleted.
    """
    items = await _lock_linked_items(db, loser_id)
    loser = await _lock_org(db, loser_id)
    before = org_values(loser)
    after = org_values(await apply_org_snapshot(db, winner, now=now))
    await _log_moves(db, items, before, after, "Power Map org merge moved assignment destinations")
    for item in items:
        item.pm_org_id = winner.pm_org_id
    await db.flush()

    loser.merged_into = winner.pm_org_id
    loser.checked_at = now
    loser.missing_since = None
    await db.flush()
    logger.warning(
        "pm_org_merged",
        extra={
            "pm_org_id": loser_id,
            "merged_into": winner.pm_org_id,
            "info_item_ids": [str(item.info_item_id) for item in items],
        },
    )
    return MERGED


async def _missing(db: AsyncSession, pm_org_id: str, now: datetime) -> str:
    row = await _lock_org(db, pm_org_id)
    if row.missing_since is None:
        row.missing_since = now
        logger.warning(
            "pm_org_missing",
            extra={"pm_org_id": pm_org_id, "name": row.name},
        )
    row.checked_at = now
    await db.flush()
    return MISSING


async def _lock_linked_items(db: AsyncSession, pm_org_id: str) -> list[InfoItem]:
    """The org's items, locked ``FOR UPDATE`` in id order (the lock ``link_org`` takes)."""
    result = await db.execute(
        select(InfoItem)
        .where(InfoItem.pm_org_id == pm_org_id)
        .order_by(InfoItem.info_item_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return list(result.scalars())


async def _lock_org(db: AsyncSession, pm_org_id: str) -> PmOrganization:
    row = await db.get(PmOrganization, pm_org_id, with_for_update=True, populate_existing=True)
    assert row is not None  # selected as linked; RESTRICT keeps it
    return row


async def _log_moves(
    db: AsyncSession,
    items: list[InfoItem],
    before: OrgValues | None,
    after: OrgValues | None,
    message: str,
) -> None:
    for item in items:
        bag = item.rep_fields or {}
        assignments = await active_assignments(db, item.info_item_id)
        moves = destination_moves(assignments, bag, bag, old_org=before, new_org=after)
        log_moves(message, item.info_item_id, moves)


def main(argv: list[str] | None = None) -> int:
    """Timer entrypoint: one sweep, exit 0.

    Dormant (exit 0, no database) when ``ARCHIVER_POWER_MAP_API_KEY`` is unset.
    An unreachable Power Map is a journald line and the next run's retry, never
    a failed unit; only a crash here exits non-zero.
    """
    parser = argparse.ArgumentParser(description="archiver Power Map org follower")
    parser.parse_args(argv)

    configure_logging()

    power_map = power_map_from_env()
    if power_map is None:
        logger.info("Power Map not configured; no orgs to refresh")
        return 0

    database_url = get_database_url()
    assert_production_db_allowed(database_url, allow_flag=os.environ.get(ALLOW_PRODUCTION_DB_ENV))

    async def _run() -> None:
        try:
            async with get_session_factory()() as db:
                await refresh_linked_orgs(db, power_map)
        finally:
            await power_map.aclose()
            await get_engine().dispose()

    asyncio.run(_run())
    return 0


if __name__ == "__main__":
    sys.exit(main())
