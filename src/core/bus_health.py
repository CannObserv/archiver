"""Broker-side bus health probes (archiver#130).

One shared probe surface, two consumers: the ``archiver-bus-health`` systemd
timer logs each finding as a WARNING journald line, and the #147 dashboard bus
panel renders the same data. WARN-only by contract - the probe observes a
broker the outbox is already designed to tolerate the loss of, so nothing here
ever blocks or restarts anything.

Why a standalone timer rather than a check inside the publisher loop: the
publisher's own "Outbox stats" line (archiver#112) rides the drain loop and
therefore vanishes exactly when the publisher is down - which is the state the
operator most needs told about. A consumer can likewise be wedged on a PEL
entry while the publisher drains normally. Broker observability stays
independent of producer liveness.

The checks, per tick:

- ``used_memory`` vs ``maxmemory`` fraction - warns *before* the ``noeviction``
  cap starts refusing ``XADD`` instance-wide, so the alert precedes the
  publisher's retry-WARNING flood rather than accompanying it.
- ``XLEN`` per stream, each threshold derived as that stream's own retention
  cap + margin, so a breach means the retention mechanism broke rather than
  that traffic grew. Three different caps apply here - see the constants below.
- last-entry age via ``XINFO STREAM`` for the permanently-groupless streams,
  which are invisible to any ``XPENDING``-based check (archiver#128).
- ``XPENDING`` on the archiver-owned consumer groups, warning only on two
  consecutive non-zero ticks - a healthy steady state is pending 0, and one
  tick of in-flight delivery is normal. Downstream services' groups are their
  own alerting problem; the broker-wide symptoms they cause (length, memory)
  are covered above.
- ``XLEN > 0`` on every ``*.dlq`` key - resting state is depth 0 (archiver#162),
  and Archiver drains every DLQ on this broker regardless of writer.
- outbox depth / oldest-unpublished age / dead-lettered count via the same
  query the #112 badge uses, run from outside the publisher process.
- disk usage on ``/`` - the AOF self-bounds, but the headroom is thinner than
  the memory headroom and nothing else alerts on it.

``content.blobs`` is deliberately absent from the inventory: that role
boundary is unqualified, with no read-only exception (CLAUDE.md). Its DLQ is
still scanned - the drainer role covers every ``*.dlq`` on the broker.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from co_core.pure.adapters.bus.streams import (
    CONTENT_ARTIFACTS,
    CONTENT_FETCH,
    CONTENT_FETCH_POLICY,
    CONTENT_REPLICATE,
    CONTENT_REVISIONS,
    INFO_CHANGES,
    INFO_REGISTRY,
    INFO_WATCH_STATUS,
    dlq_name,
)
from redis.asyncio import Redis
from redis.exceptions import RedisError, ResponseError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.changes.artifacts_consumer import CONSUMER_GROUP as ARTIFACTS_GROUP
from src.core.changes.consumer import CONSUMER_GROUP as REVISIONS_GROUP
from src.core.changes.outbox_stats import (
    BACKLOG_WARN_AGE_SECONDS,
    OutboxStats,
    collect_outbox_stats,
)
from src.core.changes.publisher import DEFAULT_STREAM_MAXLEN
from src.core.changes.registry_snapshot import DEFAULT_REGISTRY_STREAM_MAXLEN
from src.core.database import get_database_url, get_engine, get_session_factory
from src.core.db_safety import ALLOW_PRODUCTION_DB_ENV, assert_production_db_allowed
from src.core.logging import configure_logging, get_logger

# Literal rather than __name__: the timer runs this module via ``python -m``,
# where __name__ is "__main__" - a useless journald filter key.
logger = get_logger("src.core.bus_health")

# Warn while writes still succeed: past this fraction of maxmemory the next
# stop is the noeviction cap, where XADD fails instance-wide for every
# producer (archiver#129) and the publisher starts its per-row retry flood.
MEMORY_WARN_FRACTION = 0.75

# Root-filesystem headroom. The fraction matches the state observed when
# archiver#130 was un-deferred (91% used); the absolute floor catches the same
# condition on a small disk where a healthy-looking fraction hides <2 GiB.
DISK_WARN_USED_FRACTION = 0.90
DISK_WARN_MIN_FREE_BYTES = 2 * 1024**3
DISK_PATH = "/"

# Well inside systemd's default TimeoutStartSec (90s) even if every probe in
# the tick hits its ceiling, so a hung broker is reported rather than fatal.
SOCKET_CONNECT_TIMEOUT_SECONDS = 5.0
SOCKET_TIMEOUT_SECONDS = 10.0

# Both LWW streams republish their full set on `*/5 * * * *` (watcher#264/#265),
# so 3x the period of silence means the producer is down, not slow.
LWW_WARN_LAST_ENTRY_AGE_SECONDS = 900.0
# info.registry guarantees >=1 entry/hour on a non-empty corpus via the
# periodic snapshot; 2x that interval of silence means the producer is down.
# An empty stream skips the age check entirely - the corpus-size guard (#147).
REGISTRY_WARN_LAST_ENTRY_AGE_SECONDS = 7200.0

# Every length threshold is its stream's retention cap plus this margin, so a
# warning means the retention mechanism itself broke rather than that traffic
# grew. Derived from the cap constants rather than written as literals: a change
# to either default moves the threshold with it instead of leaving a stale
# number here (CR round 1, finding 1).
WARN_LENGTH_MARGIN = 0.10


def with_margin(cap: int) -> int:
    """The WARN threshold for a stream capped at ``cap`` entries."""
    return int(cap * (1 + WARN_LENGTH_MARGIN))


# Three different caps apply on this broker, and they are not interchangeable:
# - fact streams the outbox publishes ride the operator-side periodic XTRIM
#   (ARCHIVER_REDIS_STREAM_MAXLEN);
# - info.registry is excluded from that loop and capped on every publish
#   instead, because its retention floor is a consumer boot contract (#141);
# - the LWW streams are capped by their producer, Watcher (watcher#265). No
#   constant to import across the repo boundary, so the default is mirrored
#   here and named in deploy/README.md.
LWW_PRODUCER_MAXLEN = 50_000

FACT_WARN_LENGTH = with_margin(DEFAULT_STREAM_MAXLEN)
REGISTRY_WARN_LENGTH = with_margin(DEFAULT_REGISTRY_STREAM_MAXLEN)
LWW_WARN_LENGTH = with_margin(LWW_PRODUCER_MAXLEN)


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
class StreamCheck:
    """Per-stream expectations, mirroring the ``deploy/README.md`` inventory."""

    topic: str
    warn_length: int | None = None
    warn_last_entry_age_seconds: float | None = None
    pending_group: str | None = None
    # Carved out of the drain loop's trim set: capping a command stream would
    # delete commands the consumer group has not delivered and orphan the PEL
    # entries naming them. Growth is therefore expected, and a breach is a
    # volume milestone rather than a broken cap (CR round 1, finding 5).
    never_trimmed: bool = False


STREAM_CHECKS: tuple[StreamCheck, ...] = (
    StreamCheck(INFO_CHANGES, warn_length=FACT_WARN_LENGTH),
    StreamCheck(
        INFO_REGISTRY,
        warn_length=REGISTRY_WARN_LENGTH,
        warn_last_entry_age_seconds=REGISTRY_WARN_LAST_ENTRY_AGE_SECONDS,
    ),
    StreamCheck(CONTENT_FETCH, warn_length=FACT_WARN_LENGTH),
    StreamCheck(
        CONTENT_REVISIONS,
        warn_length=FACT_WARN_LENGTH,
        pending_group=REVISIONS_GROUP,
    ),
    StreamCheck(
        CONTENT_ARTIFACTS,
        warn_length=FACT_WARN_LENGTH,
        pending_group=ARTIFACTS_GROUP,
    ),
    StreamCheck(CONTENT_REPLICATE, warn_length=FACT_WARN_LENGTH, never_trimmed=True),
    StreamCheck(
        CONTENT_FETCH_POLICY,
        warn_length=LWW_WARN_LENGTH,
        warn_last_entry_age_seconds=LWW_WARN_LAST_ENTRY_AGE_SECONDS,
    ),
    StreamCheck(
        INFO_WATCH_STATUS,
        warn_length=LWW_WARN_LENGTH,
        warn_last_entry_age_seconds=LWW_WARN_LAST_ENTRY_AGE_SECONDS,
    ),
    # content.blobs: never - the role boundary has no read-only exception.
)


# --- pure evaluators ---


def evaluate_memory(*, used_memory: int, maxmemory: int) -> list[Finding]:
    """Warn on headroom pressure, and on ``maxmemory 0`` - which makes
    ``noeviction`` inert and re-opens the whole-broker OOM-kill tail (#128)."""
    if maxmemory == 0:
        return [
            Finding(
                check="memory",
                subject="redis",
                message="maxmemory is 0 - noeviction has no ceiling to enforce; "
                "see deploy/README.md (archiver#128)",
            )
        ]
    fraction = used_memory / maxmemory
    if fraction >= MEMORY_WARN_FRACTION:
        return [
            Finding(
                check="memory",
                subject="redis",
                message=f"used_memory {used_memory} is {fraction:.0%} of "
                f"maxmemory {maxmemory} (warn at {MEMORY_WARN_FRACTION:.0%}); "
                "at 100% XADD fails instance-wide for every producer",
            )
        ]
    return []


def evaluate_disk(*, total: int, free: int) -> list[Finding]:
    used_fraction = (total - free) / total
    if used_fraction >= DISK_WARN_USED_FRACTION or free < DISK_WARN_MIN_FREE_BYTES:
        return [
            Finding(
                check="disk",
                subject=DISK_PATH,
                message=f"{used_fraction:.0%} used, {free / 1024**3:.1f} GiB free "
                f"(warn at {DISK_WARN_USED_FRACTION:.0%} used or "
                f"<{DISK_WARN_MIN_FREE_BYTES / 1024**3:.0f} GiB free)",
            )
        ]
    return []


def evaluate_stream(
    check: StreamCheck, *, length: int, last_entry_ms: int | None, now_ms: int
) -> list[Finding]:
    findings: list[Finding] = []
    if check.warn_length is not None and length > check.warn_length:
        diagnosis = (
            "this stream is never trimmed by design (capping it would orphan "
            "undelivered commands), so this is a volume milestone - size the "
            "broker for it rather than looking for a broken cap"
            if check.never_trimmed
            else "the retention cap for this stream is not being applied"
        )
        findings.append(
            Finding(
                check="stream-length",
                subject=check.topic,
                message=f"XLEN {length} exceeds {check.warn_length} - {diagnosis}",
            )
        )
    if check.warn_last_entry_age_seconds is not None and length > 0 and last_entry_ms is not None:
        age = (now_ms - last_entry_ms) / 1000.0
        if age > check.warn_last_entry_age_seconds:
            findings.append(
                Finding(
                    check="stream-age",
                    subject=check.topic,
                    message=f"last entry is {age:.0f}s old "
                    f"(warn over {check.warn_last_entry_age_seconds:.0f}s) - "
                    "the producer's periodic republish has stopped",
                )
            )
    return findings


def evaluate_pending(check: StreamCheck, *, pending_now: int, pending_prev: int) -> list[Finding]:
    """Two-tick rule: one tick of non-zero pending is in-flight delivery;
    non-zero across two consecutive ticks means the consumer is wedged or its
    database is down (archiver#139)."""
    if pending_now > 0 and pending_prev > 0:
        return [
            Finding(
                check="pending",
                subject=f"{check.topic}/{check.pending_group}",
                message=f"XPENDING {pending_now} for two consecutive ticks "
                f"(was {pending_prev}) - consumer wedged or DB down; messages "
                "are accruing unconsumed while the stream keeps accepting them",
            )
        ]
    return []


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


def _entry_ms(entry_id: str | bytes) -> int:
    raw = entry_id.decode() if isinstance(entry_id, bytes) else entry_id
    return int(raw.split("-", 1)[0])


async def _collect_stream(
    client: Redis, check: StreamCheck, previous_pending: dict[str, int]
) -> tuple[list[Finding], dict[str, int]]:
    findings: list[Finding] = []
    pending: dict[str, int] = {}

    if not await client.exists(check.topic):
        # A stream nothing has written yet is dormancy, not a fault - the age
        # and length checks both need entries to exist before they mean much.
        return findings, pending

    info = await client.xinfo_stream(check.topic)
    length = int(info.get("length", 0))
    last_entry = info.get("last-entry")
    last_entry_ms = _entry_ms(last_entry[0]) if last_entry else None
    now_ms = int(time.time() * 1000)
    findings.extend(
        evaluate_stream(check, length=length, last_entry_ms=last_entry_ms, now_ms=now_ms)
    )

    if check.pending_group is not None:
        key = f"{check.topic}/{check.pending_group}"
        try:
            summary = await client.xpending(check.topic, check.pending_group)
        except (ResponseError, IndexError):
            # Real Redis raises NOGROUP (a ResponseError); fakeredis's reply
            # for a missing group instead crashes redis-py's parse_xpending
            # with IndexError. Both mean the same thing here.
            findings.append(
                Finding(
                    check="group-missing",
                    subject=check.topic,
                    message=f"consumer group {check.pending_group!r} does not "
                    "exist - the consumer never provisioned itself",
                )
            )
        else:
            pending_now = int(summary["pending"])
            pending[key] = pending_now
            findings.extend(
                evaluate_pending(
                    check,
                    pending_now=pending_now,
                    pending_prev=previous_pending.get(key, 0),
                )
            )
    return findings, pending


async def _collect_memory(client: Redis) -> list[Finding]:
    try:
        info = await client.info("memory")
    except ResponseError:
        # A server without INFO (fakeredis) is a probe limitation, not a broker
        # fault. Connection failures propagate to the caller's broker finding.
        return []
    return evaluate_memory(
        used_memory=int(info.get("used_memory", 0)),
        maxmemory=int(info.get("maxmemory", 0)),
    )


async def _collect_dlqs(client: Redis) -> list[Finding]:
    """Scan is filtered to stream keys, and each XLEN is guarded anyway: a stray
    non-stream ``*.dlq`` key must not raise WRONGTYPE out of this function,
    where it would be reported as "broker unreachable" and discard every other
    finding on the tick (CR round 1, finding 7)."""
    findings: list[Finding] = []
    async for key in client.scan_iter(match="*.dlq", _type="stream"):
        topic = key.decode() if isinstance(key, bytes) else key
        try:
            depth = await client.xlen(topic)
        except ResponseError:
            continue
        if depth > 0:
            findings.append(
                Finding(
                    check="dlq",
                    subject=topic,
                    message=f"depth {depth} - resting state is 0; every entry "
                    "is operator-actionable (archiver#162 drain procedure)",
                )
            )
    return findings


async def collect_group_lag(client: Redis) -> list[GroupLag]:
    """Live lag for the archiver-owned groups, for the #147 dashboard panel.

    Narrower than a probe tick on purpose: a page load pays two ``XPENDING``
    and two ``XLEN`` calls rather than the whole ~25-command inventory sweep.

    Two contracts differ from the timer's collector, both because the caller is
    a request handler rather than a WARN-only log line:

    - a broker error **propagates**. The timer folds an outage into a finding
      because a journald line is its only output; the panel has to badge
      "could not measure" differently from "measured zero", which is the whole
      complaint in #147.
    - the two-tick pending rule is deliberately absent. It debounces a periodic
      alarm; an operator reading a dashboard is looking at one instant and can
      refresh, so a raw depth is the honest number to show.
    """
    lags: list[GroupLag] = []
    for check in STREAM_CHECKS:
        if check.pending_group is None:
            continue
        try:
            summary = await client.xpending(check.topic, check.pending_group)
        except (ResponseError, IndexError):
            # NOGROUP from real Redis, IndexError from fakeredis - see
            # _collect_stream. Distinct from 0: nothing provisioned the group.
            pending = None
        else:
            pending = int(summary["pending"])
        lags.append(
            GroupLag(
                topic=check.topic,
                group=check.pending_group,
                pending=pending,
                # XLEN on a missing key is 0, which is the right answer: a DLQ
                # is created by its first quarantine, so absent means empty.
                dlq_depth=await client.xlen(dlq_name(check.topic)),
            )
        )
    return lags


async def collect_broker_findings(
    client: Redis, *, previous_pending: dict[str, int]
) -> tuple[list[Finding], dict[str, int]]:
    """All Redis-side probes. An unreachable broker is itself the finding, and
    ``previous_pending`` passes through untouched so an outage does not reset
    the two-tick grace window."""
    try:
        findings = await _collect_memory(client)
        pending: dict[str, int] = {}
        for check in STREAM_CHECKS:
            stream_findings, stream_pending = await _collect_stream(client, check, previous_pending)
            findings.extend(stream_findings)
            pending.update(stream_pending)
        findings.extend(await _collect_dlqs(client))
    except (RedisError, OSError) as e:  # ConnectionError is an OSError subclass
        return (
            [
                Finding(
                    check="broker",
                    subject="redis",
                    message=f"broker unreachable or probe failed: {e!r}",
                )
            ],
            dict(previous_pending),
        )
    return findings, pending


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


# --- state file (two-tick pending memory across oneshot runs) ---


def load_state(path: Path) -> dict[str, int]:
    try:
        raw = json.loads(path.read_text())
    except (FileNotFoundError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {str(k): int(v) for k, v in raw.items() if isinstance(v, int)}


def save_state(path: Path, pending: dict[str, int]) -> None:
    path.write_text(json.dumps(pending))


# --- orchestration ---


async def run_once(
    client: Redis,
    *,
    session_factory: async_sessionmaker[AsyncSession] | None,
    state_path: Path,
    disk_usage: Callable[[str], tuple[int, int, int]] = shutil.disk_usage,
) -> list[Finding]:
    """One probe tick: collect everything, WARN per finding, one summary line.

    ``session_factory=None`` skips the outbox probe (tests, broker-only runs);
    the timer always passes one. ``disk_usage`` is injectable so tests do not
    inherit the host's real headroom.
    """
    previous_pending = load_state(state_path)
    findings, pending = await collect_broker_findings(client, previous_pending=previous_pending)
    if session_factory is not None:
        findings.extend(await collect_outbox_findings(session_factory))

    total, _used, free = disk_usage(DISK_PATH)
    findings.extend(evaluate_disk(total=total, free=free))

    save_state(state_path, pending)

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
    here, not a broker state) surfaces as a non-zero exit."""
    parser = argparse.ArgumentParser(description="archiver bus health probe")
    parser.add_argument("--state-file", type=Path, required=True)
    args = parser.parse_args(argv)

    configure_logging()

    redis_url = os.environ.get("ARCHIVER_REDIS_URL")
    if not redis_url:
        # Same dormancy contract as scripts/check_redis_floor.sh: no bus
        # configured means nothing to probe, not a failure.
        logger.info("ARCHIVER_REDIS_URL not set - bus dormant, probe skipped")
        return 0

    database_url = get_database_url()
    assert_production_db_allowed(database_url, allow_flag=os.environ.get(ALLOW_PRODUCTION_DB_ENV))

    async def _run() -> None:
        # Bounded sockets: a hung (rather than refusing) broker would otherwise
        # block until systemd's TimeoutStartSec kills the unit, turning the
        # WARN-only "broker unreachable" finding into a failed unit in exactly
        # the degraded state this probe exists to report (CR round 1, finding
        # 3). The timeouts surface as RedisTimeoutError, which the collector
        # already renders as that finding.
        client = Redis.from_url(
            redis_url,
            socket_connect_timeout=SOCKET_CONNECT_TIMEOUT_SECONDS,
            socket_timeout=SOCKET_TIMEOUT_SECONDS,
        )
        try:
            await run_once(
                client,
                session_factory=get_session_factory(),
                state_path=args.state_file,
            )
        finally:
            # Both pools go down inside the loop that created them; an asyncpg
            # pool reclaimed during loop teardown emits "Event loop is closed"
            # noise into the journald stream this unit keeps clean (CR round 1,
            # finding 6).
            await client.aclose()
            await get_engine().dispose()

    asyncio.run(_run())
    return 0


if __name__ == "__main__":
    sys.exit(main())
