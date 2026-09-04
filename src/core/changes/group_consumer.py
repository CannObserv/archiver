"""The consumer-group loop, shared by every stream Archiver reads with a group.

Extracted from ``consumer.py`` when ``content.artifacts`` became the second such
stream (archiver#170). What lives here is the *delivery* machinery — read, claim,
quarantine, ack, back off, re-arm the group — and none of the domain: a caller
supplies a ``handle`` coroutine that decides one message and returns whether it
may be acked.

Copying this would have been the alternative, and it is the wrong one for a
specific reason: nearly every line encodes an incident or a review finding
(re-arming ``ensure_group`` after a flush, following ``XAUTOCLAIM``'s cursor past
the first window, reading the row id before the commit, throttling the error log).
A copy inherits those once and then drifts away from them silently, which is the
same failure mode the no-cross-repo-mirror rule exists to prevent.

**What a caller still owns**, because it is genuinely per-stream:

- the group name — a wire contract with the broker's monitoring
- the ``handle`` coroutine, and which of its exceptions mean *poison* (dead-letter
  and move on) rather than *retry later* (leave pending)
- whether an unknown payload type on the stream is ackable
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from co_core.pure.adapters.bus.exceptions import BusMessageAnomaly
from co_core_aio.bus import AsyncBusConsumer, BusMessage, from_wire

from src.core.changes import read_windows
from src.core.changes.backoff import (
    ERROR_BACKOFF_BASE_SECONDS,
    ERROR_LOG_EVERY,
    error_backoff_seconds,
)
from src.core.changes.diagnostics import error_text
from src.core.logging import get_logger

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = get_logger(__name__)

# Read one at a time. ``AsyncBusConsumer.read`` decodes inside the call, so a
# poison frame in a ``count > 1`` batch raises before the well-formed messages
# are returned; at one per read, the frame that raised is unambiguous. Production
# volume is a handful of WatchedItems, so batching buys nothing worth that.
READ_COUNT = 1
READ_BLOCK_MS = read_windows.GROUP_READ_BLOCK_MS

# Reclaim entries a consumer took and never acked (it died mid-message). Long
# enough that it never races a live consumer's in-flight message.
CLAIM_MIN_IDLE_MS = 60_000
CLAIM_INTERVAL_ITERATIONS = 12
CLAIM_COUNT = 10
# Bound the quarantine scan so a pathological PEL cannot hold the loop forever;
# at CLAIM_COUNT per pass this covers 1000 pending entries, and the residue is
# logged rather than silently skipped.
MAX_QUARANTINE_PASSES = 100

_TRUTHY = frozenset({"1", "true", "yes", "on"})

# One message's decision: True = settled (ack it), False = leave pending for
# redelivery. Raising one of the caller's ``poison_errors`` means "this can never
# be used" and dead-letters the frame.
MessageHandler = Callable[[BusMessage], Awaitable[bool]]


def consumer_enabled(raw: str | None) -> bool:
    """Whether ``ARCHIVER_BUS_CONSUMER`` opts this process into a group.

    A gate the publisher never needed. Producing to the bus from a stray process
    is noisy; *consuming* removes messages from the group, so any process that
    sources ``/etc/archiver/.env`` — an agent shell, a one-off script, a debug
    run — would join as a competing consumer and silently swallow messages into
    whatever database it happens to hold. Presence of ``ARCHIVER_REDIS_URL`` is
    therefore not sufficient authority; only ``deploy/archiver.service`` sets
    this, and it must never appear in an env file (the
    ``ARCHIVER_ALLOW_PRODUCTION_DB`` precedent).
    """
    return (raw or "").strip().lower() in _TRUTHY


def resolve_consumer_name(group: str) -> str:
    """Name this reader within the group - the group name, dashed, plus a slot.

    ``archiver.revisions`` -> ``archiver-revisions-1``. **Stable across restarts
    on purpose** (archiver#156). The previous ``{hostname}:{pid}`` spelling minted
    a fresh registration on every restart that received a message and nothing ever
    called ``XGROUP DELCONSUMER``, so orphans accumulated without bound - seven on
    the production broker by 2026-08-27, six of them dead. A stable name makes a
    restart *reuse* its registration, so the leak cannot recur rather than needing
    to be periodically swept, and it needs no shutdown hook that a ``SIGKILL``
    would skip anyway.

    It also fixes a misattribution: this VM's hostname is literally ``watcher``
    (it is shared with the Watcher service), so Archiver's own consumers read as
    Watcher's in ``XINFO`` output on a broker all three services share.
    ``archiver-revisions-1`` matches Watcher's own ``watcher-1`` convention on
    ``content.blobs``.

    Derived from the group rather than written out per caller so the next group
    consumer inherits the convention instead of copying a literal.

    The ``-1`` is a slot, not decoration: ``deploy/archiver.service`` runs uvicorn
    with no ``--workers``, so there is exactly one member and the pid carried no
    information a log line does not. A multi-consumer deployment assigns ``-2``
    upward - and must first raise ``quarantine_undecodable``'s ``min_idle_time``,
    for the reason recorded in that docstring.
    """
    return f"{group.replace('.', '-')}-1"


@dataclass(frozen=True, slots=True)
class GroupConsumer:
    """The group reader plus the three things every recovery path also needs.

    ``AsyncBusConsumer`` exposes neither its own consumer name nor its topic and
    group, and the raw ``XAUTOCLAIM`` in ``quarantine_undecodable`` needs all
    three. Bundling them rather than reaching into the driver's internals — they
    always travel together anyway.

    ``name`` must be unique across concurrent *members* of the group, so
    ``XAUTOCLAIM`` can tell a dead member's pending entries from a live one's. It
    is deliberately **not** unique across restarts of the same member - see
    ``resolve_consumer_name``.
    """

    bus: AsyncBusConsumer
    name: str
    client: Redis
    topic: str
    group: str


def build_group_consumer(
    client: Redis, *, topic: str, group: str, consumer_name: str | None = None
) -> GroupConsumer:
    """Build a group reader for ``topic``."""
    name = consumer_name or resolve_consumer_name(group)
    return GroupConsumer(
        bus=AsyncBusConsumer(client, topic=topic, group=group, consumer=name),
        name=name,
        client=client,
        topic=topic,
        group=group,
    )


async def ensure_group(consumer: GroupConsumer) -> None:
    """Create the group at ``0``, not ``$``.

    ``$`` delivers only what is published after group creation, so anything
    already on the stream when this service first starts is dropped — exactly the
    window the epic's "land the consumer before the producer cuts over" ordering
    exists to close. Replay from the beginning is safe because every handler here
    is idempotent under redelivery, so ``0`` costs a few wasted lookups and buys
    the ordering guarantee.
    """
    await consumer.bus.ensure_group(start_id="0")


async def _process(
    consumer: GroupConsumer,
    handle: MessageHandler,
    message: BusMessage,
    poison_errors: tuple[type[BaseException], ...],
) -> bool:
    """Handle one decoded message and settle it if the outcome is terminal.

    Returns whether the message was settled — acked after a successful write, or
    dead-lettered when it can never be used. The ack strictly follows the
    handler's commit; a failure in between leaves the entry pending and the next
    delivery repeats an idempotent write.
    """
    try:
        ackable = await handle(message)
    except poison_errors as exc:
        logger.error(
            "Quarantining unusable message",
            # error_text, not repr: a consumer has no last_error column, so this
            # line is the ONLY record a quarantined message leaves behind, and the
            # remedy usually lives on the chained cause.
            extra={
                "message_id": message.message_id,
                "topic": consumer.topic,
                "error": error_text(exc),
            },
            exc_info=exc,
        )
        await consumer.bus.dead_letter(message.message_id, dict(message.fields))
        return True

    if ackable:
        await consumer.bus.ack(message.message_id)
    return ackable


async def quarantine_undecodable(consumer: GroupConsumer) -> int:
    """DLQ pending entries that will not decode. Returns how many were moved.

    ``AsyncBusConsumer.read`` decodes inside the call, so ``from_wire`` raises
    *before* any message id reaches the caller — there is nothing to hand
    ``dead_letter``, and the entry is already in the group's PEL where a
    subsequent read or claim hits it again identically. Left alone that is an
    unbounded crash-backoff loop over one bad frame, the failure the publisher's
    build-phase dead-letter exists to prevent (archiver#107).

    So the recovery goes back to the raw stream: claim the group's pending
    entries, re-attempt the decode per entry, and route only the ones that fail
    to the topic's DLQ. Entries that decode are left pending — they are picked up
    by the next read or by ``reclaim_stale``.

    The scan follows ``XAUTOCLAIM``'s cursor to the end of the PEL rather than
    stopping at the first ``CLAIM_COUNT`` window: after a backlog (a DB outage,
    say) the poison frame can sit well past entry ten, and a single-window scan
    would leave it there for as many passes as it takes the window to advance.

    ``min_idle_time=0`` claims regardless of age, and following the cursor means
    the scan is **bounded only by the pass ceiling** — up to
    ``MAX_QUARANTINE_PASSES * CLAIM_COUNT`` entries. With one process per host
    (what ``deploy/archiver.service`` runs, no ``--workers``) that is free. With
    two, one poison frame would pull the *whole* group's in-flight PEL to a single
    worker rather than a slice of it. **A multi-consumer deployment must raise
    ``min_idle_time`` above the expected per-message processing time** before
    adding workers — that is the change this constant is waiting on, recorded here
    because this is where it would be made.
    """
    quarantined = 0
    cursor = "0-0"
    for _ in range(MAX_QUARANTINE_PASSES):
        next_cursor, entries, _deleted = await consumer.client.xautoclaim(
            consumer.topic,
            consumer.group,
            consumer.name,
            min_idle_time=0,
            start_id=cursor,
            count=CLAIM_COUNT,
        )
        for entry_id, raw_fields in entries:
            message_id = _as_str(entry_id)
            fields = {_as_str(k): _as_str(v) for k, v in raw_fields.items()}
            try:
                from_wire(fields, topic=consumer.topic, message_id=message_id)
            except BusMessageAnomaly as exc:
                logger.error(
                    "Dead-lettering undecodable frame",
                    extra={
                        "message_id": message_id,
                        "topic": consumer.topic,
                        "error": error_text(exc),
                    },
                    exc_info=exc,
                )
                await consumer.bus.dead_letter(message_id, fields)
                quarantined += 1
        cursor = _as_str(next_cursor)
        # "0-0" is XAUTOCLAIM's end-of-PEL sentinel; an empty page ends it too.
        if cursor == "0-0" or not entries:
            break
    else:
        logger.warning(
            "Quarantine scan hit its pass ceiling; pending entries remain unscanned",
            extra={
                "passes": MAX_QUARANTINE_PASSES,
                "quarantined": quarantined,
                "topic": consumer.topic,
            },
        )
    return quarantined


def _as_str(value: bytes | str) -> str:
    """Redis returns bytes unless the client decodes responses; accept both."""
    return value.decode() if isinstance(value, bytes) else value


async def consume_once(
    *,
    consumer: GroupConsumer,
    handle: MessageHandler,
    poison_errors: tuple[type[BaseException], ...] = (),
    count: int = READ_COUNT,
    block_ms: int | None = None,
) -> int:
    """Read and process up to ``count`` messages. Returns how many were settled.

    *Settled* covers every terminal disposition — written, deduped, dropped as
    unknown, or quarantined — rather than only the ones that wrote a row; the
    count exists to pace the loop, and all of them mean "do not redeliver this".

    A decode failure is not raised at the caller: the offending frame is
    quarantined and this call returns 0, so the loop keeps its cadence and the
    next iteration reads past it.
    """
    try:
        messages = await consumer.bus.read(count=count, block_ms=block_ms)
    except BusMessageAnomaly:
        await quarantine_undecodable(consumer)
        return 0

    settled = 0
    for message in messages:
        try:
            if await _process(consumer, handle, message, poison_errors):
                settled += 1
        except Exception:
            # Un-acked on purpose: the entry stays in the PEL and is redelivered.
            logger.exception(
                "Failed to process message; leaving it pending",
                extra={"message_id": message.message_id, "topic": consumer.topic},
            )
    return settled


async def reclaim_stale(
    *,
    consumer: GroupConsumer,
    handle: MessageHandler,
    poison_errors: tuple[type[BaseException], ...] = (),
    min_idle_ms: int = CLAIM_MIN_IDLE_MS,
) -> int:
    """Process entries a dead consumer left pending. Returns how many were settled.

    Without this, a crash between read and ack parks the message in a PEL that
    nothing else reads: ``XREADGROUP`` with ``>`` only ever delivers entries no
    member has seen, so a pending one is invisible to every subsequent read.

    Since archiver#156 the name is stable across restarts, so the usual case is a
    consumer reclaiming **its own** pre-restart entry - ``XAUTOCLAIM`` scans the
    whole group PEL regardless of owner, the claimant included, so that needs no
    special handling. ``min_idle_ms`` is what keeps it from racing a live
    member's in-flight message.
    """
    try:
        messages = await consumer.bus.claim_stale(min_idle_ms=min_idle_ms, count=CLAIM_COUNT)
    except BusMessageAnomaly:
        await quarantine_undecodable(consumer)
        return 0

    settled = 0
    for message in messages:
        try:
            if await _process(consumer, handle, message, poison_errors):
                settled += 1
        except Exception:
            logger.exception(
                "Failed to process reclaimed message; leaving it pending",
                extra={"message_id": message.message_id, "topic": consumer.topic},
            )
    return settled


async def run(
    *,
    consumer: GroupConsumer,
    handle: MessageHandler,
    poison_errors: tuple[type[BaseException], ...] = (),
    stop_event: asyncio.Event | None = None,
    block_ms: int = READ_BLOCK_MS,
    claim_interval_iterations: int = CLAIM_INTERVAL_ITERATIONS,
    claim_min_idle_ms: int = CLAIM_MIN_IDLE_MS,
    error_backoff_base: float = ERROR_BACKOFF_BASE_SECONDS,
) -> None:
    """Loop until ``stop_event`` is set, consuming ``consumer.topic``.

    The blocking read paces the loop, so there is no idle sleep; only a failing
    iteration backs off (escalating, capped, logged every ``ERROR_LOG_EVERY``-th
    so a sustained broker outage cannot flood the journal).
    ``asyncio.CancelledError`` propagates for shutdown; everything else is logged
    and the loop continues.

    **Group creation is inside the loop, and any failure re-arms it.** Hoisting
    the ``ensure_group`` call above the loop looks tidier and breaks two ways that
    are hard to see afterwards:

    - A broker that is down at *startup* kills the task outright. That is not
      hypothetical — ``archiver.service`` orders after ``redis-server`` only
      softly (``Wants=``), on the reasoning that the outbox tolerates a late
      broker; a consumer would not have.
    - Flushing the stream destroys its groups, after which every read raises
      ``NOGROUP`` forever. ``deploy/README.md`` treats flushing streams as
      routine, so this is a state operators are *instructed* to produce.

    Both end the same way — no ingestion, silently, while the stream keeps
    growing. ``ensure_group`` is idempotent (``BUSYGROUP`` is swallowed), so
    re-asserting costs one round trip on the pass after a failure and nothing at
    all on the happy path.
    """
    stop_event = stop_event or asyncio.Event()
    logger.info(
        "Bus consumer starting",
        # The consumer name, not just the group: registration happens on delivery,
        # so a healthy consumer on a quiet stream is absent from XINFO CONSUMERS
        # and this line is the only place a deploy can be verified from
        # (deploy/README.md, archiver#156).
        extra={
            "group": consumer.group,
            "topic": consumer.topic,
            "consumer": consumer.name,
        },
    )

    iteration = 0
    consecutive_failures = 0
    group_ready = False
    while not stop_event.is_set():
        try:
            if not group_ready:
                await ensure_group(consumer)
                group_ready = True
            await consume_once(
                consumer=consumer,
                handle=handle,
                poison_errors=poison_errors,
                block_ms=block_ms,
            )
            iteration += 1
            if claim_interval_iterations and iteration % claim_interval_iterations == 0:
                await reclaim_stale(
                    consumer=consumer,
                    handle=handle,
                    poison_errors=poison_errors,
                    min_idle_ms=claim_min_idle_ms,
                )
            if consecutive_failures:
                # Positive recovery signal at the same filter level as the
                # failures, so both edges of an incident are visible.
                logger.warning(
                    "Bus consumer recovered",
                    extra={"topic": consumer.topic, "after_failures": consecutive_failures},
                )
            consecutive_failures = 0
            continue
        except asyncio.CancelledError:
            raise
        except Exception:
            consecutive_failures += 1
            # Re-arm group creation. The cheapest correct response to *any*
            # failure, because the two states that need it — broker unreachable,
            # group destroyed by a flush — are not distinguishable from the
            # exception type in a way worth branching on, and re-asserting an
            # existing group is a no-op.
            group_ready = False
            if consecutive_failures == 1 or consecutive_failures % ERROR_LOG_EVERY == 0:
                logger.exception(
                    "Bus consumer loop error; backing off",
                    extra={
                        "topic": consumer.topic,
                        "consecutive_failures": consecutive_failures,
                    },
                )

        delay = error_backoff_seconds(consecutive_failures, error_backoff_base)
        await asyncio.wait(
            [asyncio.create_task(stop_event.wait())],
            timeout=delay,
            return_when=asyncio.FIRST_COMPLETED,
        )
