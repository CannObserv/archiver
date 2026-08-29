"""Outbox-to-Redis-Stream publisher background task.

Drains pending rows from ``information.changes_outbox`` and publishes each to its
declared topic on Redis via the shared co-core bus driver
(``co_core_aio.bus.AsyncBusPublisher`` executing a ``BusPublish`` effect). The
wire envelope is built by the pure ``co_core.pure.adapters.bus.envelope.to_wire``
serializer - archiver no longer hand-rolls the XADD field map (archiver#106).
The transactional outbox stays here (the producer-side delivery guarantee);
co-core provides only the publish effect/driver the drain loop calls.

Best-effort retry: a *transient* publish failure (Redis down/slow/loading)
increments ``publish_attempts`` and records ``last_error``; the row stays
unpublished and is re-attempted on the next loop iteration - indefinitely, so a
long outage never drops a valid event. A *deterministic* build failure - an
unknown ``event_type`` or an unvalidatable payload - is dead-lettered immediately
(``dead_lettered_at`` stamped), so a poison row cannot spin forever flooding the
log. A high attempt ceiling is a backstop that dead-letters only a *non-transient*
publish failure that persists past it (archiver#107).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from co_core.effects.bus import BusPublish
from co_core.pure.adapters.bus.envelope import payload_from_dict, to_wire
from co_core_aio.bus import AsyncBusPublisher
from redis.exceptions import BusyLoadingError
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import OutOfMemoryError as RedisOutOfMemoryError
from redis.exceptions import TimeoutError as RedisTimeoutError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.changes.backoff import (
    ERROR_BACKOFF_BASE_SECONDS,
    ERROR_LOG_EVERY,
    error_backoff_seconds,
)
from src.core.changes.diagnostics import error_text
from src.core.changes.outbox_prune import prune_outbox
from src.core.changes.outbox_stats import log_outbox_stats
from src.core.logging import get_logger
from src.core.models import ChangesOutboxRow

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = get_logger(__name__)

DEFAULT_BATCH_SIZE = 100
ACTIVE_INTERVAL_SECONDS = 0.25
IDLE_INTERVAL_SECONDS = 1.0

# Publish-phase failures that are *transient* (broker down / slow / loading) and
# must retry indefinitely. These are EXEMPT from the dead-letter ceiling below, so
# a long-but-genuine Redis outage can never silently drop valid events - the
# primary protection against a data-loss cliff (CR #2). redis-py's own error types
# are disjoint from the builtins, so both are listed. Everything else reaching the
# publish except (e.g. a server-side ResponseError / WRONGTYPE) is treated as
# possibly-permanent and subject to the ceiling.
#
# ``OutOfMemoryError`` is the odd one out - it is a ``ResponseError`` subclass, so
# the "everything else is possibly-permanent" rule above would otherwise catch it.
# It is listed transient deliberately (archiver#128): Archiver operates a *shared*
# broker under ``maxmemory-policy noeviction`` with an explicit ``maxmemory`` cap
# (``deploy/redis-server.dropin.conf``), so an unrelated stream filling the
# instance surfaces here as ``OOM command not allowed`` on a perfectly valid
# event. That is an operator-resolvable outage, not poison - treating it as
# permanent would dead-letter good ``info.changes`` events during someone else's
# memory incident, which is exactly the loss the ceiling exemption exists to
# prevent.
#
# NOTE (co-core coupling, CR #10): this gate assumes
# ``AsyncBusPublisher.execute`` propagates the underlying redis exception types
# *unwrapped* (the current co-core-aio behavior - a raw redis ConnectionError from
# XADD surfaces here as-is). If co-core ever wraps publish failures in its own
# ``BusError``-style type, a real outage would fall through to the ceiling and the
# cliff #2 fixed would reopen - this tuple must then track that wrapper type.
_TRANSIENT_PUBLISH_ERRORS: tuple[type[BaseException], ...] = (
    ConnectionError,  # builtin
    TimeoutError,  # builtin
    RedisConnectionError,
    RedisTimeoutError,
    BusyLoadingError,
    RedisOutOfMemoryError,
)

# Attempt ceiling for NON-transient publish failures - a pure defense-in-depth
# backstop (archiver#107, CR #2). Deterministic poison (unknown event_type /
# unvalidatable payload) is dead-lettered on the FIRST failure in the build phase,
# so this ceiling is not the primary mechanism. Transient errors (above) are
# exempt, so this bites only a NON-transient failure that persists - and it is set
# very high so that even a *misclassified* transient error (one not in the tuple)
# gets generous headroom before being dropped. At ~1 attempt/idle-tick this is on
# the order of a day of continuous failure, not the ~17 min of the prior 1000.
#
# Accepted cost (CR #8): a genuinely *permanent* non-transient publish error (e.g.
# a WRONGTYPE from a misconfigured stream key) logs a WARNING every drain until it
# reaches this ceiling - up to ~a day of WARNING-spam before it dead-letters. That
# is the deliberate trade for never dropping a valid event on a long transient
# outage; such permanent non-transient errors are rare, and the loop still
# terminates (unlike the unbounded pre-#107 spin).
MAX_PUBLISH_ATTEMPTS = 100_000

# The single Redis Stream Archiver produces to (both event types share it). Used
# as the operator-side XTRIM target; the emit sites hardcode the same literal.
CHANGE_STREAM_TOPIC = "info.changes"

# Trim the stream every N drain-loop iterations when a cap is configured. With
# the loop's sub-second/idle cadence this bounds growth without an XTRIM every
# tick. Archiver operates the broker (archiver#109), so capping is its job.
#
# Periodic XTRIM is a CHOICE, not an absence (archiver#138 - the co-core 0.7 bump
# falsified the note that used to sit here). ``BusPublish`` does carry ``maxlen`` /
# ``approximate`` since cannobserv#285, and ``AsyncBusPublisher.execute`` passes
# both to XADD. That arg exists for the *config/state* stream kind, whose consumers
# rebuild current state by replaying from ``0-0`` - there retention is a consumer
# contract, so it has to ride on the publish. ``info.changes`` is a *fact* stream:
# nothing replays it to reconstruct state (the archiver#137 epic says so in as many
# words - "a log is not state"), so its cap is pure operator-side housekeeping and
# belongs on the operator's cadence, not welded to every publish. Switching to
# XADD MAXLEN would also silently re-scope the cap to topics Archiver publishes to,
# losing the pre-existing-stream case `run` covers via ``trim_topic``.
TRIM_INTERVAL_ITERATIONS = 20

# Default approximate cap on info.changes when ARCHIVER_REDIS_STREAM_MAXLEN is
# unset. See resolve_stream_maxlen for the parse contract.
DEFAULT_STREAM_MAXLEN = 100_000

# Cadence of the periodic "Outbox stats" line (archiver#112): depth, oldest-row
# age, dead-lettered count. Low enough to be journald-greppable during an
# incident, high enough to be noise-free when healthy. The first line is emitted
# on the loop's first iteration so a restart re-states the backlog immediately.
STATS_LOG_INTERVAL_SECONDS = 300.0

# Cadence of the published-row retention pass (archiver#189). The third periodic
# side-job on this loop, and deliberately the slowest: a published row's only
# residual value is forensic, so nothing is served by deleting it promptly. The
# pass rides here rather than a systemd timer because a timer would need
# ARCHIVER_ALLOW_PRODUCTION_DB, and a third sanctioned holder of a write-capable
# production-DB opt-in is too high a price for deleting delivered rows. There is
# no coverage hole: a published row can only exist if this loop ran. Like the
# stats line, the first pass fires immediately, so a restart is not a way to
# skip retention forever.
PRUNE_INTERVAL_SECONDS = 3600.0

# Whole-batch failure backoff (CR #13). When drain_once itself raises (DB down,
# session-factory failure - distinct from a per-row publish failure it swallows),
# the loop escalates its sleep exponentially from ERROR_BACKOFF_BASE_SECONDS up to
# a cap, and logs only every ERROR_LOG_EVERY-th consecutive failure so a sustained
# outage cannot flood the journal at 1/idle-tick. The counter resets on the first
# successful drain, which also emits a recovery log. The backoff base is its own
# knob, decoupled from idle_interval (poll cadence vs error cadence - CR #15).
#
# The schedule itself lives in src/core/changes/backoff.py - the bus consumer runs
# the same one, and a copy stops tracking the original silently (#139 CR).


def _next_delay(
    *,
    consecutive_failures: int,
    published: int,
    active_interval: float,
    idle_interval: float,
    backoff_base: float,
) -> float:
    """Pick the loop's sleep before the next drain.

    A whole-batch failure streak wins (escalating backoff); otherwise pace on
    forward progress - ``active_interval`` when rows were published this cycle,
    ``idle_interval`` when the batch was empty or every row failed (CR #10/#16).
    """
    if consecutive_failures:
        return error_backoff_seconds(consecutive_failures, backoff_base)
    return active_interval if published else idle_interval


def resolve_stream_maxlen(raw: str | None) -> int | None:
    """Parse the ``ARCHIVER_REDIS_STREAM_MAXLEN`` knob into a trim cap.

    Returns the positive cap, or ``None`` to disable trimming (a ``<= 0`` value).
    Unset falls back to ``DEFAULT_STREAM_MAXLEN`` (trimming on by default). A
    **malformed** value also falls back to the default and logs a warning - it
    must never raise, because ``main.lifespan`` resolves this inside the broad
    guard that would otherwise disable the entire publisher over a retention
    typo (CR #109).
    """
    if raw is None:
        return DEFAULT_STREAM_MAXLEN
    try:
        value = int(raw)
    except ValueError:
        logger.warning(
            "Invalid ARCHIVER_REDIS_STREAM_MAXLEN; falling back to default",
            extra={"value": raw, "default": DEFAULT_STREAM_MAXLEN},
        )
        return DEFAULT_STREAM_MAXLEN
    return value if value > 0 else None


def _dead_letter(row: ChangesOutboxRow, exc: Exception, *, reason: str) -> None:
    """Move ``row`` to its terminal (dead-lettered) state - archiver#107.

    Stamps ``dead_lettered_at`` (so the drain loop stops selecting it) and records
    ``last_error``; ``payload`` is left intact for post-mortem. Logs at ERROR
    because a poison row means a producer wrote something unpublishable - an
    operator signal, unlike a transient retry. Does NOT touch ``publish_attempts``;
    the caller owns that counter (it is incremented on the failing branch before
    this is called).
    """
    rendered = error_text(exc)
    row.last_error = rendered[:1000]
    row.dead_lettered_at = datetime.now(UTC)
    event_type = row.payload.get("event_type") if isinstance(row.payload, dict) else None
    logger.error(
        "Dead-lettering outbox row",
        extra={
            "row_id": str(row.id),
            "topic": row.topic,
            "event_type": event_type,
            "reason": reason,
            "publish_attempts": row.publish_attempts,
            # Kept alongside exc_info deliberately: this is the one-line, greppable
            # form that matches what landed in last_error, where exc_info is the
            # multi-line traceback. Same content, two different read paths.
            "error": rendered,
        },
        # The chain is truncated at 1000 chars on the row; the log keeps the
        # full traceback so a poison row stays diagnosable from journald alone.
        exc_info=exc,
    )


async def drain_once(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    publisher: AsyncBusPublisher,
    batch_size: int = DEFAULT_BATCH_SIZE,
    seen_topics: set[str] | None = None,
    topic_maxlen: Mapping[str, int] | None = None,
) -> int:
    """Drain at most ``batch_size`` unpublished rows.

    Returns the number of rows **successfully published** this call (not the
    number attempted). The caller (``run``) paces on this so an all-failing batch
    reports zero progress and the loop backs off to its idle interval instead of
    busy-waiting at the active interval (CR #10).

    When ``seen_topics`` is provided, each successfully-published ``row.topic`` is
    added to it, so the caller (``run``) can trim every stream it has actually
    produced to - not just the canonical one - should the topic set ever grow
    beyond ``info.changes``.

    Delivery is **at-least-once**: the ``XADD`` and the ``commit`` below are not
    atomic, so a crash after a successful publish but before commit leaves the row
    ``published_at IS NULL`` and it is re-published next drain - a duplicate stream
    entry. Consumers MUST dedupe on the co-core idempotency ``key`` in the wire
    envelope; that is also why a re-publish is safe to retry freely (CR #12).
    """
    published = 0
    async with session_factory() as session:
        result = await session.execute(
            select(ChangesOutboxRow)
            .where(
                ChangesOutboxRow.published_at.is_(None),
                ChangesOutboxRow.dead_lettered_at.is_(None),
            )
            .order_by(ChangesOutboxRow.created_at)
            .limit(batch_size)
        )
        rows = list(result.scalars())
        if not rows:
            return 0
        for row in rows:
            # Build phase - reconstruct the typed payload + wire envelope via
            # co-core's shared ``payload_from_dict`` (archiver#108: the local
            # ``_PAYLOAD_BY_EVENT_TYPE`` copy is gone - it dispatches through the
            # same private table + raises the ``BusMessageAnomaly`` family, so
            # there is no parallel table to drift). This is pure (no I/O), so ANY
            # failure here is *deterministic*: identical every loop. Catch broadly
            # and dead-letter immediately - a narrower catch would let an
            # unanticipated exception type escape per-row handling and wedge the
            # whole batch in a crash-backoff loop (CR #1). Known shapes are a
            # missing/unknown ``event_type`` or an unvalidatable payload (all
            # ``BusMessageAnomaly`` subclasses), but the guarantee is "no build
            # error spins forever".
            try:
                fields = to_wire(payload_from_dict(row.payload))
            except Exception as exc:
                row.publish_attempts = (row.publish_attempts or 0) + 1
                _dead_letter(row, exc, reason="unpublishable_payload")
                continue

            # Publish phase - a failure here (Redis/network) is usually *transient*:
            # retry on the next drain. Transient errors are exempt from the ceiling
            # (retry forever, no data-loss cliff); only a NON-transient failure that
            # persists past the ceiling is dead-lettered as a backstop (archiver#107,
            # CR #2).
            try:
                # at-least-once boundary: if the process dies between this XADD
                # and the commit below, the row re-publishes next drain - safe
                # only because consumers dedupe on the envelope idempotency key.
                # Config/state streams (info.registry) carry retention ON the
                # publish: their consumers replay from 0-0, so the cap is a
                # consumer contract (co-core streams taxonomy), not operator
                # housekeeping. Fact streams pass None and keep the XTRIM loop.
                maxlen = (topic_maxlen or {}).get(row.topic)
                bus_result = await publisher.execute(
                    BusPublish(topic=row.topic, fields=fields, maxlen=maxlen)
                )
                row.published_at = datetime.now(UTC)
                row.bus_message_id = bus_result.bus_message_id
                row.last_error = None
                published += 1
                if seen_topics is not None:
                    seen_topics.add(row.topic)
            except Exception as exc:
                row.publish_attempts = (row.publish_attempts or 0) + 1
                transient = isinstance(exc, _TRANSIENT_PUBLISH_ERRORS)
                if not transient and row.publish_attempts >= MAX_PUBLISH_ATTEMPTS:
                    _dead_letter(row, exc, reason="attempts_exhausted")
                else:
                    row.last_error = error_text(exc)[:1000]
                    logger.warning(
                        "Failed to publish outbox row",
                        extra={
                            "row_id": str(row.id),
                            "topic": row.topic,
                            "publish_attempts": row.publish_attempts,
                            "transient": transient,
                            "error": repr(exc),
                        },
                    )
        await session.commit()
        return published


async def trim_stream(client: Redis, topic: str, maxlen: int) -> None:
    """Cap ``topic`` to roughly ``maxlen`` entries via an approximate ``XTRIM``.

    Operator-side retention (archiver#109): with no consumer yet, entries
    accumulate on ``info.changes``, so Archiver (the broker operator) bounds the
    stream itself. ``approximate=True`` (Redis ``MAXLEN ~``) trims whole
    macro-nodes - cheap, may leave slightly more than ``maxlen``. Best-effort:
    a failing trim is logged and swallowed so it never breaks the drain loop.
    """
    try:
        await client.xtrim(topic, maxlen=maxlen, approximate=True)
    except Exception:
        # exc_info so a *persistent* trim failure (bad type, NOPERM, misconfig)
        # is distinguishable from a transient redis-down blip - the swallow
        # otherwise leaves no trace to diagnose an unbounded stream.
        logger.warning(
            "Stream trim failed",
            extra={"topic": topic, "maxlen": maxlen},
            exc_info=True,
        )


async def run(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    publisher: AsyncBusPublisher,
    batch_size: int = DEFAULT_BATCH_SIZE,
    active_interval: float = ACTIVE_INTERVAL_SECONDS,
    idle_interval: float = IDLE_INTERVAL_SECONDS,
    stop_event: asyncio.Event | None = None,
    redis_client: Redis | None = None,
    stream_maxlen: int | None = None,
    trim_topic: str = CHANGE_STREAM_TOPIC,
    trim_interval_iterations: int = TRIM_INTERVAL_ITERATIONS,
    error_backoff_base: float = ERROR_BACKOFF_BASE_SECONDS,
    no_trim_topics: frozenset[str] = frozenset(),
    topic_maxlen: Mapping[str, int] | None = None,
    stats_interval: float | None = STATS_LOG_INTERVAL_SECONDS,
    retention_days: int | None = None,
    prune_interval: float = PRUNE_INTERVAL_SECONDS,
) -> None:
    """Loop forever (until ``stop_event`` is set), draining the outbox.

    Sleeps ``active_interval`` when a drain made progress (published > 0),
    ``idle_interval`` when it drained nothing or every row failed (CR #10), and an
    escalating capped backoff (from ``error_backoff_base``) while ``drain_once``
    itself keeps raising (CR #13). Repeated whole-batch failures are logged capped
    (every ``ERROR_LOG_EVERY``-th), and the first success after a streak emits a
    ``WARNING`` recovery log. Handles ``asyncio.CancelledError`` by re-raising; all
    other exceptions are logged and the loop continues.

    When ``redis_client`` and a positive ``stream_maxlen`` are supplied, the loop
    caps every stream it has produced to via ``trim_stream`` every
    ``trim_interval_iterations`` iterations - operator-side retention
    (archiver#109). It trims ``trim_topic`` (the canonical ``info.changes``) until
    a different ``row.topic`` is observed, then trims each observed topic too, so
    an added stream cannot grow unbounded silently. Left unset (the dormant or
    unconfigured case), no trimming occurs.

    Every ``stats_interval`` seconds (first iteration immediately, ``None``
    disables) the loop emits the periodic "Outbox stats" line via
    ``log_outbox_stats`` - producer-side observability (archiver#112). Failures
    inside it are swallowed there, so the cadence can never break the drain.

    Every ``prune_interval`` seconds (first iteration immediately) it runs the
    published-row retention pass via ``prune_outbox`` - archiver#189. Left at the
    default ``retention_days=None`` (the dormant or disabled-knob case) nothing
    is pruned. Failures are swallowed there too, on the same reasoning.
    """
    stop_event = stop_event or asyncio.Event()
    seen_topics: set[str] = set()
    iteration = 0
    consecutive_failures = 0
    last_stats_log: float | None = None
    last_prune: float | None = None
    while not stop_event.is_set():
        try:
            published = await drain_once(
                session_factory=session_factory,
                publisher=publisher,
                batch_size=batch_size,
                seen_topics=seen_topics,
                topic_maxlen=topic_maxlen,
            )
            if consecutive_failures:
                # Positive signal that the loop is healthy again (CR #14) - the
                # absence of error logs alone is ambiguous with "still backed off".
                # WARNING (not INFO) so both edges of an incident are visible at
                # the same filter level as the failure logs (CR #17).
                logger.warning(
                    "Outbox publisher recovered",
                    extra={"after_failures": consecutive_failures},
                )
            consecutive_failures = 0
        except asyncio.CancelledError:
            raise
        except Exception:
            consecutive_failures += 1
            # Cap the log flood: on a sustained outage log only the first failure
            # and then every ERROR_LOG_EVERY-th, carrying the running count.
            if consecutive_failures == 1 or consecutive_failures % ERROR_LOG_EVERY == 0:
                logger.exception(
                    "Outbox publisher loop error; backing off",
                    extra={"consecutive_failures": consecutive_failures},
                )
            published = 0

        iteration += 1
        if stats_interval is not None and (
            last_stats_log is None or time.monotonic() - last_stats_log >= stats_interval
        ):
            await log_outbox_stats(session_factory)
            last_stats_log = time.monotonic()

        if retention_days is not None and (
            last_prune is None or time.monotonic() - last_prune >= prune_interval
        ):
            await prune_outbox(session_factory, retention_days=retention_days)
            last_prune = time.monotonic()

        if (
            redis_client is not None
            and stream_maxlen
            and stream_maxlen > 0
            and iteration % trim_interval_iterations == 0
        ):
            # Trim every stream produced to; fall back to the canonical topic so
            # a pre-existing stream is bounded even before the first publish.
            # no_trim_topics carve out the config/state streams: their retention
            # is a consumer contract riding BusPublish.maxlen (above). One global
            # MAXLEN sized for the fact stream would silently break the
            # replay-from-0-0 convergence floor (archiver#141).
            for topic in (seen_topics or {trim_topic}) - no_trim_topics:
                await trim_stream(redis_client, topic, stream_maxlen)

        delay = _next_delay(
            consecutive_failures=consecutive_failures,
            published=published,
            active_interval=active_interval,
            idle_interval=idle_interval,
            backoff_base=error_backoff_base,
        )
        await asyncio.wait(
            [asyncio.create_task(stop_event.wait())],
            timeout=delay,
            return_when=asyncio.FIRST_COMPLETED,
        )
