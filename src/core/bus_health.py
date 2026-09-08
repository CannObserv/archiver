"""Archiver's bus-health surface: the outbox probe and the dashboard's group lag.

Originally the whole broker-side probe (archiver#130). archiver#193 Phase 3
split it: everything that measured **the broker's host** - memory headroom,
per-stream ``XLEN`` against retention caps, last-entry age, the two-tick
``XPENDING`` rule, the DLQ sweep, and disk - moved to CannObserv/broker with
the host it measures (D6). Archiver stopped being that host, and those checks
had begun silently reporting archiver's disk and archiver's systemd.

What is left is what could not move:

- ``collect_outbox_findings`` queries ``information.changes_outbox``. Nothing
  broker-side about it, and the reason it exists survives the split intact:
  the publisher's own "Outbox stats" line (archiver#112) rides the drain loop
  and therefore vanishes exactly when the publisher is down - which is the
  state the operator most needs told about. That is why ``archiver-bus-health``
  is **reduced** rather than retired in favour of the dashboard panel: a
  journald line fires whether or not anyone is looking at a page.
- ``collect_group_lag`` feeds the archiver#147 dashboard bus panel.
  ``XPENDING`` against a remote broker is an ordinary client call.

Alerting on those groups is not this module's job any more. The broker's probe
warns on non-zero pending across two consecutive ticks; this collector reports
one instant, for a page an operator can refresh.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING

from co_core.pure.adapters.bus.streams import (
    CONTENT_ARTIFACTS,
    CONTENT_REVISIONS,
    dlq_name,
    stream_kind,
)
from redis.exceptions import ResponseError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.changes.artifacts_consumer import CONSUMER_GROUP as ARTIFACTS_GROUP
from src.core.changes.consumer import CONSUMER_GROUP as REVISIONS_GROUP
from src.core.changes.outbox_stats import (
    BACKLOG_WARN_AGE_SECONDS,
    OutboxStats,
    collect_outbox_stats,
)
from src.core.database import get_database_url, get_engine, get_session_factory
from src.core.db_safety import ALLOW_PRODUCTION_DB_ENV, assert_production_db_allowed
from src.core.logging import configure_logging, get_logger

if TYPE_CHECKING:  # pragma: no cover - annotation only
    # Type-only: this module builds no Redis client. The one that used to live
    # in ``main`` went to CannObserv/broker with the probes that needed it
    # (archiver#193 Phase 3); ``collect_group_lag`` is handed the lifespan's
    # client by its caller.
    from redis.asyncio import Redis

# Literal rather than __name__: the timer runs this module via ``python -m``,
# where __name__ is "__main__" - a useless journald filter key.
logger = get_logger("src.core.bus_health")


@dataclass(frozen=True)
class Finding:
    """One WARN-worthy observation; ``check`` names the probe, ``subject`` the
    stream/group/resource it fired on."""

    check: str
    subject: str
    message: str


@dataclass(frozen=True)
class GroupLag:
    """Live depths for one archiver-owned consumer group (archiver#147).

    ``pending is None`` means the group does not exist on the broker - the
    consumer never provisioned itself. Kept distinct from ``0`` because they
    look identical to an operator and mean opposite things.
    """

    topic: str
    group: str
    pending: int | None
    dlq_depth: int


@dataclass(frozen=True)
class OwnedGroup:
    """One consumer group archiver runs a consumer for.

    Replaces the ``StreamCheck`` this file used to carry. That dataclass
    described a *stream* - its retention cap, its last-entry age threshold,
    whether it is trimmed - and every one of those fields measured the broker,
    so they left with it (archiver#193 D6). What archiver still needs is the
    much smaller thing: which groups are ours to report lag for.
    """

    topic: str
    group: str

    def __post_init__(self) -> None:
        """Refuse a group on a config/state stream.

        A group on a config/state stream accumulates a PEL nothing drains:
        every worker needs every message, so no reader acks on behalf of the
        others. co-core has always stated the rule; since >=0.13.1 the taxonomy
        is machine-readable via ``stream_kind``, so the rule can be enforced
        here rather than resting on whoever edits ``OWNED_GROUPS`` next knowing
        it (cannobserv#384).

        Stronger than the guard it replaces: ``StreamCheck.pending_group`` was
        optional, so this ran only on the rows that had one. Every
        ``OwnedGroup`` names a group by construction, so it always runs.

        Deliberately a hard ``ValueError`` at import time rather than a logged
        finding: this is a statement about the stream's *kind*, which cannot
        become true at runtime, so there is nothing an operator could act on
        and no reason to let the process start.

        A topic ``stream_kind`` cannot classify - a synthetic name in a test -
        is left alone rather than rejected. The guard exists to catch a *known*
        config/state stream being given a group, and it has no opinion about a
        name outside the taxonomy.

        ``stream_kind`` signals "not canonical" by raising ``ValueError``, and
        co-core publishes no public set of canonical topics to test membership
        against (``_STREAM_KINDS`` is private), so the check has to run through
        the exception. That makes this guard **fail open** if co-core ever
        raises ``ValueError`` here for a reason other than an unknown topic;
        ``test_every_owned_topic_is_classifiable`` turns that into a caught
        test failure rather than a silently disabled guard.
        """
        try:
            kind = stream_kind(self.topic)
        except ValueError:
            return
        if kind == "config_state":
            raise ValueError(
                f"{self.topic} is a config_state stream and must not carry a "
                f"consumer group (got {self.group!r})"
            )


OWNED_GROUPS: tuple[OwnedGroup, ...] = (
    OwnedGroup(CONTENT_REVISIONS, REVISIONS_GROUP),
    OwnedGroup(CONTENT_ARTIFACTS, ARTIFACTS_GROUP),
)
"""The groups archiver consumes, and only those.

No rows for the streams archiver merely publishes to: those carried length and
age thresholds, which measure the broker's retention, and moved to
CannObserv/broker. ``content.blobs`` appears here for the same reason it never
appeared in the probe - the role boundary is unqualified (CLAUDE.md): it does
not.
"""


# --- pure evaluators ---


def evaluate_outbox(stats: OutboxStats) -> list[Finding]:
    """Same thresholds as the #112 surfaces, evaluated from outside the
    publisher process - the backlog this catches is the one the in-loop stats
    line cannot report because the loop is not running."""
    findings: list[Finding] = []
    age = stats.oldest_unpublished_age_seconds
    if age is not None and age > BACKLOG_WARN_AGE_SECONDS:
        findings.append(
            Finding(
                check="outbox",
                subject="changes_outbox",
                message=f"oldest unpublished row is {age:.0f}s old "
                f"({stats.unpublished_count} unpublished) - publisher down, "
                "wedged, or broker unreachable",
            )
        )
    if stats.dead_lettered_count:
        findings.append(
            Finding(
                check="outbox",
                subject="changes_outbox",
                message=f"{stats.dead_lettered_count} dead-lettered row(s) "
                "awaiting operator triage (archiver#107)",
            )
        )
    return findings


# --- collectors ---


async def collect_group_lag(client: Redis) -> list[GroupLag]:
    """Live lag for the archiver-owned groups, for the #147 dashboard panel.

    Two contracts differ from the broker repo's timer, both because the caller
    is a request handler rather than a WARN-only log line:

    - a broker error **propagates**. A journald line can fold an outage into a
      finding; the panel has to badge "could not measure" differently from
      "measured zero", which is the whole complaint in #147.
    - the two-tick pending rule is deliberately absent. It debounces a periodic
      alarm; an operator reading a dashboard is looking at one instant and can
      refresh, so a raw depth is the honest number to show.
    """
    lags: list[GroupLag] = []
    for owned in OWNED_GROUPS:
        try:
            summary = await client.xpending(owned.topic, owned.group)
        except (ResponseError, IndexError):
            # Real Redis raises NOGROUP (a ResponseError); fakeredis's reply
            # for a missing group instead crashes redis-py's parse_xpending
            # with IndexError. Distinct from 0: nothing provisioned the group.
            pending = None
        else:
            pending = int(summary["pending"])
        lags.append(
            GroupLag(
                topic=owned.topic,
                group=owned.group,
                pending=pending,
                # XLEN on a missing key is 0, which is the right answer: a DLQ
                # is created by its first quarantine, so absent means empty.
                dlq_depth=await client.xlen(dlq_name(owned.topic)),
            )
        )
    return lags


async def collect_outbox_findings(
    session_factory: async_sessionmaker[AsyncSession],
) -> list[Finding]:
    try:
        async with session_factory() as session:
            stats = await collect_outbox_stats(session)
    except Exception as e:  # noqa: BLE001 - any DB failure is the finding
        return [
            Finding(
                check="outbox",
                subject="changes_outbox",
                message=f"outbox stats query failed: {e!r}",
            )
        ]
    return evaluate_outbox(stats)


# --- orchestration ---


async def run_once(*, session_factory: async_sessionmaker[AsyncSession]) -> list[Finding]:
    """One probe tick: query the outbox, WARN per finding, one summary line.

    Stateless since archiver#193 Phase 3. The state file existed to carry the
    two-tick ``XPENDING`` rule between oneshot runs, and that rule went to the
    broker repo with the groups it debounced.
    """
    findings = await collect_outbox_findings(session_factory)

    for finding in findings:
        logger.warning(
            f"Bus health: {finding.message}",
            extra={"check": finding.check, "subject": finding.subject},
        )
    summary = logger.warning if findings else logger.info
    summary("Bus health summary", extra={"finding_count": len(findings)})
    return findings


def main(argv: list[str] | None = None) -> int:
    """Timer entrypoint. Always exits 0 once the probe ran - WARN-only means a
    finding is a journald line, never a failed unit. Only a probe crash (a bug
    here, not an outbox state) surfaces as a non-zero exit.

    No ``ARCHIVER_REDIS_URL`` check and no Redis client since archiver#193
    Phase 3: the broker is watched from its own node, and a bus-dormant
    archiver still has an outbox worth reporting on. The old dormancy skip
    would have made this unit report nothing on exactly such a host.
    """
    parser = argparse.ArgumentParser(description="archiver outbox health probe")
    parser.parse_args(argv)

    configure_logging()

    database_url = get_database_url()
    assert_production_db_allowed(database_url, allow_flag=os.environ.get(ALLOW_PRODUCTION_DB_ENV))

    async def _run() -> None:
        try:
            await run_once(session_factory=get_session_factory())
        finally:
            # The pool goes down inside the loop that created it; an asyncpg
            # pool reclaimed during loop teardown emits "Event loop is closed"
            # noise into the journald stream this unit keeps clean.
            await get_engine().dispose()

    asyncio.run(_run())
    return 0


if __name__ == "__main__":
    sys.exit(main())
