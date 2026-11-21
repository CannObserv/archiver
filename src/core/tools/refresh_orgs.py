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

**The check-in (archiver#476).** Each configured run checks in once to Status's
``co-archiver-pm-org-refresh`` monitor (:mod:`src.core.status_checkin`): ``ok``
when every linked org answered (none linked included, so a quiet host never goes
``missing``); ``alert`` on the first run where any got no answer, unreached
orgs of a stopped sweep counted (D1). It reports *Archiver's* view of Power Map,
over the proxy with Archiver's key; Power Map's own health is ``co-power-map``'s
(D2). The check-in never changes the exit code (BACKUP.md's rule): an
unreachable Power Map, a missing monitor id or key, a Status that refuses - all
exit 0, logged. A crash sends nothing, and the monitor goes ``missing``.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import random
import sys
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

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
    PowerMapReader,
    PowerMapUnavailableError,
    Snapshot,
    power_map_from_env,
)
from src.core.power_map.snapshots import OrgUnnamedError, apply_org_snapshot, org_values
from src.core.rep_fields import OrgValues
from src.core.status_checkin import (
    CREDENTIAL_NAME,
    DEFAULT_STATUS_URL,
    MONITOR_ID_PATTERN,
    STATUS_URL_ENV,
    post_checkin,
    read_key,
)
from src.core.tools.set_rep_fields import (
    active_assignments,
    assignment_refusals,
    destination_moves_for_item,
    log_moves,
)

# Literal rather than __name__: the timer runs this module via ``python -m``,
# where __name__ is "__main__" - a useless journald filter key.
logger = get_logger("src.core.tools.refresh_orgs")

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
#: once; longer ends the sweep, and the next hourly run is the retry (CR 4).
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

#: ``co-archiver-pm-org-refresh``, tenant ``co-archiver`` (archiver#476).
MONITOR_ID_ENV = "CO_ARCHIVER_PM_ORG_REFRESH_MONITOR_ID"
CREDENTIALS_DIRECTORY_ENV = "CREDENTIALS_DIRECTORY"
#: Which side the check-in reports (D2), on every body.
VIEW = (
    "Archiver's view of Power Map (its public address, with Archiver's key); "
    "Power Map's own health is co-power-map's power-map-ready"
)


@dataclass(frozen=True)
class Sweep:
    """One sweep's result: the linked orgs, each checked id's outcome, the first error."""

    linked: int
    outcomes: dict[str, str] = field(default_factory=dict)
    #: The first ``PowerMapUnavailableError.reason``: a fixed vocabulary, no URL, no key.
    first_error: str | None = None

    @property
    def unanswered(self) -> int:
        """Linked orgs with no answer: ``unavailable``, or never reached by a stopped sweep."""
        return self.linked - sum(1 for o in self.outcomes.values() if o != UNAVAILABLE)


@dataclass(frozen=True)
class Verdict:
    """What to tell ``co-archiver-pm-org-refresh``, and the variables its template renders."""

    kind: Literal["ok", "unreachable", "test"]
    body: str
    linked: int = 0
    unanswered: int = 0
    error: str = ""

    @property
    def status(self) -> Literal["ok", "alert"]:
        """The check-in's ``status``."""
        return "ok" if self.kind == "ok" else "alert"

    def variables(self) -> dict[str, str]:
        """Every variable on every check-in, so the monitor's template always renders."""
        return {
            "kind": self.kind,
            "linked": str(self.linked),
            "unanswered": str(self.unanswered),
            "error": self.error,
            "body": self.body,
        }

    def metadata(self) -> dict[str, str] | None:
        """An alert's fault (status#28); an ok names none."""
        return {"fault": self.kind} if self.status == "alert" else None


def verdict(sweep: Sweep) -> Verdict:
    """``alert`` on the first run any linked org got no answer (D1); else ``ok``."""
    if not sweep.unanswered:
        orgs = "the 1 linked org" if sweep.linked == 1 else f"all {sweep.linked} linked orgs"
        return Verdict("ok", f"{VIEW}: {orgs} answered", sweep.linked)
    error = sweep.first_error or "no answer"
    body = (
        f"{VIEW}: {sweep.unanswered} of {sweep.linked} linked orgs got no answer "
        f"(first: {error}); their pm_organizations snapshots are not refreshed"
    )
    return Verdict("unreachable", body, sweep.linked, sweep.unanswered, error)


def deliberate_alert() -> Verdict:
    """The alert ``--test-alert`` sends: proves the channels, asks Power Map nothing."""
    return Verdict(
        "test",
        f"{VIEW}: a test alert from archiver's org follower, sent by hand; Power Map was not asked",
        error="test",
    )


async def refresh_linked_orgs(
    db: AsyncSession,
    power_map: PowerMapReader,
    *,
    pace_seconds: float = PACE_SECONDS,
    sleep: Sleep = asyncio.sleep,
) -> Sweep:
    """Check every linked org once, in random order; returns the :class:`Sweep`.

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
        if fetch.halted or failures >= MAX_CONSECUTIVE_FAILURES:
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
    return Sweep(len(rows), outcomes, fetch.first_error)


class _Fetcher:
    """``get_org`` paced for the read bucket, waiting out one short ``Retry-After``.

    ``halted`` is set by a ``Retry-After`` too long to wait out: the sweep stops
    rather than send more requests into the rate limit.
    """

    def __init__(self, power_map: PowerMapReader, *, pace_seconds: float, sleep: Sleep) -> None:
        self._power_map = power_map
        self._pace_seconds = pace_seconds
        self._sleep = sleep
        self._sent = False
        self.halted = False
        self.first_error: str | None = None

    async def get_org(self, pm_org_id: str, etag: str | None = None) -> OrgResult:
        for attempt in range(2):  # the first try, and one retry after a short wait
            try:
                return await self._get(pm_org_id, etag)
            except PowerMapUnavailableError as e:
                if e.retry_after is not None and e.retry_after > MAX_RETRY_AFTER_SECONDS:
                    self.halted = True  # on the retry too (CR 12)
                if e.retry_after is None or self.halted or attempt:
                    self.first_error = self.first_error or e.reason
                    raise
                await self._sleep(e.retry_after)
        raise AssertionError("unreachable: the second attempt returns or raises")

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
            extra={"pm_org_id": pm_org_id, "org_name": row.name},
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
    """Log each item's moves, and the assignments the change stopped rendering (CR 5).

    Power Map's change applies either way (Q4). An assignment that rendered
    under the old org and does not under the new one is warned about now - its
    next occasion is skipped. One that was already broken is not the change's
    doing and is not blamed on it (CR 10). Neither reaches
    ``destination_moves_for_item``, which raises on an unrenderable new bag. The
    logged paths are the item's latest revision's (archiver#333).
    """
    for item in items:
        bag = item.rep_fields or {}
        assignments = await active_assignments(db, item.info_item_id)
        refusals = assignment_refusals(assignments, bag, org=after)
        already = {r.assignment_id for r in assignment_refusals(assignments, bag, org=before)}
        broken = [r for r in refusals if r.assignment_id not in already]
        if broken:
            logger.warning(
                "Power Map org change leaves assignments that cannot render",
                extra={
                    "info_item_id": str(item.info_item_id),
                    "refusals": [
                        {"assignment_id": str(r.assignment_id), "code": r.code, "errors": r.errors}
                        for r in broken
                    ],
                },
            )
        refused = {r.assignment_id for r in refusals}
        renderable = [(a, spec) for a, spec in assignments if a.id not in refused]
        moves, _ = await destination_moves_for_item(
            db, item.info_item_id, renderable, bag, bag, old_org=before, new_org=after
        )
        log_moves(message, item.info_item_id, moves)


def checkin(v: Verdict, *, environ: Mapping[str, str]) -> bool:
    """One check-in to ``co-archiver-pm-org-refresh``; True when Status took it.

    **Never raises** (backup's ``checkin``): whatever goes wrong is logged and
    swallowed, so the sweep's exit code stands. No monitor id is a warning, not
    an error: the unit ships without one until Status provisions it.
    """
    monitor_id = environ.get(MONITOR_ID_ENV, "").strip()
    if not monitor_id:
        logger.warning(
            f"No {MONITOR_ID_ENV}: no check-in sent, and a Power Map outage will not be noticed"
        )
        return False
    if not MONITOR_ID_PATTERN.fullmatch(monitor_id):
        logger.error(f"Check-in not sent: {MONITOR_ID_ENV} is not a ULID")
        return False
    credentials = environ.get(CREDENTIALS_DIRECTORY_ENV, "").strip()
    key = read_key(Path(credentials) if credentials else None)
    if not key:
        logger.error(f"Check-in not sent: no {CREDENTIAL_NAME} credential")
        return False
    try:
        code = post_checkin(
            environ.get(STATUS_URL_ENV) or DEFAULT_STATUS_URL,
            monitor_id,
            key,
            v.status,
            v.variables(),
            metadata=v.metadata(),
        )
    except Exception as e:  # CheckinFailed, or anything httpx raises outside HTTPError
        logger.error(
            "Power Map org refresh check-in failed",
            extra={"status": v.status, "error": f"{type(e).__name__}: {e}"},
        )
        return False
    logger.info(
        "Power Map org refresh checked in",
        extra={"status": v.status, "kind": v.kind, "checkin": code},
    )
    return True


def main(argv: list[str] | None = None) -> int:
    """Timer entrypoint: one sweep, one check-in, exit 0.

    Dormant (exit 0, no database, no check-in) when ``ARCHIVER_POWER_MAP_API_KEY``
    is unset. An unreachable Power Map is an ``alert`` check-in and the next
    run's retry, never a failed unit; the check-in never changes the exit code;
    only a crash here exits non-zero. ``--test-alert`` sends one alert and asks
    Power Map and the database nothing: exit 0 when Status took it, else 1.
    """
    parser = argparse.ArgumentParser(description="archiver Power Map org follower")
    parser.add_argument(
        "--test-alert",
        action="store_true",
        help="send one test alert to the monitor; ask Power Map and the database nothing",
    )
    args = parser.parse_args(argv)

    configure_logging()

    if args.test_alert:
        return 0 if checkin(deliberate_alert(), environ=os.environ) else 1

    power_map = power_map_from_env()
    if power_map is None:
        logger.info("Power Map not configured; no orgs to refresh")
        return 0

    database_url = get_database_url()
    assert_production_db_allowed(database_url, allow_flag=os.environ.get(ALLOW_PRODUCTION_DB_ENV))

    async def _run() -> Sweep:
        try:
            async with get_session_factory()() as db:
                return await refresh_linked_orgs(db, power_map)
        finally:
            await power_map.aclose()
            await get_engine().dispose()

    sweep = asyncio.run(_run())
    checkin(verdict(sweep), environ=os.environ)
    return 0


if __name__ == "__main__":
    sys.exit(main())
