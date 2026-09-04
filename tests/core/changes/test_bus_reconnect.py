"""What the consumer loops do when the broker connection drops mid-flight.

archiver#193 Phase 1 item 2. The epic reads the two group consumers and the
``info.watch-status`` tail as "not obviously covered", against a publisher half
that demonstrably is. Reading the loops, that is too pessimistic: all three carry
the same ``except Exception`` / escalating-backoff / ``ERROR_LOG_EVERY`` shape as
the publisher, and the group loop additionally re-arms ``ensure_group``.

What was genuinely missing is a test. Every existing failure test in
``test_consumer.py`` and ``test_watch_status_consumer.py`` drives a **database**
failure, which enters through a different path than a broker one: a DB error is
raised by the handler, inside ``consume_once``, where dedicated logic settles or
rewinds it. A broker error is raised by ``read`` itself and propagates to
``run``'s handler, which nothing exercised. So these pin behaviour that already
holds rather than changing it - which is the point, because the behaviour becomes
load-bearing the moment the broker is a ~40 ms relay away (CannObserv/broker#1)
instead of loopback.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import NoPermissionError

from src.core.changes import group_consumer, watch_status_consumer

# A backoff base small enough that a test does not wait on it. The escalation
# curve itself is covered by tests/core/changes/test_backoff.py.
_FAST_BACKOFF = 0.001


@dataclass
class _FlakyBus:
    """An ``AsyncBusConsumer`` stand-in that fails a set number of reads first.

    ``read`` yields before returning, and that is not cosmetic. In production the
    blocking ``XREADGROUP`` is what paces this loop - ``run`` has no idle sleep on
    its happy path, by design. A fake that returns without awaiting therefore
    turns the loop into a tight spin that never cedes control, and any test
    driving it from a second task hangs rather than fails. The fake stops the
    loop itself for the same reason: it is the only participant that knows a read
    happened.
    """

    failures: int
    error: BaseException
    stop_after_reads: int
    stop_event: asyncio.Event = field(default_factory=asyncio.Event)
    ensure_group_calls: list[str] = field(default_factory=list)
    reads: int = 0

    async def ensure_group(self, *, start_id: str) -> None:
        self.ensure_group_calls.append(start_id)

    async def read(self, *, count: int, block_ms: int | None) -> list[Any]:
        await asyncio.sleep(0)
        self.reads += 1
        if self.reads >= self.stop_after_reads:
            self.stop_event.set()
        if self.reads <= self.failures:
            raise self.error
        return []

    async def claim_stale(self, *, min_idle_ms: int, count: int) -> list[Any]:
        await asyncio.sleep(0)
        return []


def _consumer(bus: _FlakyBus) -> group_consumer.GroupConsumer:
    return group_consumer.GroupConsumer(
        bus=bus,  # type: ignore[arg-type]
        name="archiver-revisions-1",
        client=object(),  # type: ignore[arg-type]
        topic="content.revisions",
        group="archiver.revisions",
    )


async def _drive(bus: _FlakyBus, **kwargs: Any) -> None:
    """Run the loop until the bus has served ``bus.stop_after_reads`` reads.

    ``wait_for`` is a backstop, not the mechanism: if the loop ever stops
    consulting ``stop_event`` this fails in ten seconds instead of hanging the
    suite.
    """
    await asyncio.wait_for(
        group_consumer.run(
            consumer=_consumer(bus),
            handle=lambda _m: (_ for _ in ()).throw(AssertionError("no messages expected")),
            stop_event=bus.stop_event,
            error_backoff_base=_FAST_BACKOFF,
            **kwargs,
        ),
        timeout=10,
    )


@pytest.mark.parametrize(
    "error",
    [
        RedisConnectionError("Error 111 connecting to broker:6379."),
        TimeoutError("Timeout reading from broker:6379"),
        NoPermissionError("NOPERM this user has no permissions to run the 'xreadgroup' command"),
    ],
    ids=["connection_refused", "read_timeout", "acl_denied"],
)
@pytest.mark.asyncio
async def test_group_loop_survives_a_broker_error_and_keeps_reading(error: BaseException) -> None:
    """The loop must not die on a dropped connection - it is the only ingestion path.

    ``NoPermissionError`` is in here because CannObserv/broker#1 D3 puts an ACL
    in front of the broker, and a consumer meeting a mistyped rule must degrade
    to a backing-off loop that recovers when the rule is fixed, not to a dead
    task. There is no consumer-side equivalent of the publisher's transient
    classification, and this is why one is not needed: the loop's handler is
    already error-agnostic.
    """
    bus = _FlakyBus(failures=2, error=error, stop_after_reads=4)
    await _drive(bus)
    assert bus.reads == 4  # kept reading past both failures


@pytest.mark.asyncio
async def test_group_loop_re_arms_ensure_group_after_a_broker_error() -> None:
    """Re-arming is what makes a flush survivable, and it is easy to "tidy" away.

    ``ensure_group`` is called once on the happy path and again after *any*
    failure. Hoisting it out of the loop - the obvious refactor - would leave
    every read raising ``NOGROUP`` forever after an operator flushes the stream,
    which ``deploy/README.md`` treats as routine. Pinned so the docstring
    arguing against the hoist has a test behind it.
    """
    bus = _FlakyBus(failures=1, error=RedisConnectionError("broker gone"), stop_after_reads=3)
    await _drive(bus)
    assert len(bus.ensure_group_calls) >= 2, "the failure did not re-arm group creation"
    assert set(bus.ensure_group_calls) == {"0"}, "must re-create at 0, never $"


@pytest.mark.asyncio
async def test_group_loop_logs_the_failure_once_then_reports_recovery(monkeypatch) -> None:
    """Both edges of an incident are visible: one ERROR in, one WARNING out.

    The first failure logs immediately (not on the ``ERROR_LOG_EVERY``-th), so a
    brief blip is not silent; a sustained outage is then damped. Recovery logs at
    WARNING, the same filter level as the failure, so an operator tailing at
    WARNING sees the incident close rather than just stop.
    """
    exceptions: list[dict] = []
    warnings: list[dict] = []
    monkeypatch.setattr(
        group_consumer.logger,
        "exception",
        lambda msg, *a, **k: exceptions.append(k.get("extra", {})),
    )
    monkeypatch.setattr(
        group_consumer.logger,
        "warning",
        lambda msg, *a, **k: warnings.append(k.get("extra", {})),
    )

    bus = _FlakyBus(failures=1, error=RedisConnectionError("broker gone"), stop_after_reads=3)
    await _drive(bus)

    assert len(exceptions) == 1
    assert exceptions[0]["consecutive_failures"] == 1
    assert any(w.get("after_failures") == 1 for w in warnings), (
        "no recovery line - an operator cannot tell the outage ended"
    )


# ---------------------------------------------------------------------------
# The info.watch-status tail: the cursor is the thing at risk
# ---------------------------------------------------------------------------


@dataclass
class _FlakyReader:
    """An ``AsyncBusTailReader`` stand-in with a real in-memory cursor.

    Yields and self-stops for the reason given on ``_FlakyBus``.
    """

    failures: int
    error: BaseException
    stop_after_reads: int | None = None
    stop_event: asyncio.Event = field(default_factory=asyncio.Event)
    cursor: str = "1788222000571-2"
    reads: int = 0

    def seek(self, message_id: str) -> None:
        self.cursor = message_id

    async def read(self, *, count: int, block_ms: int | None) -> list[Any]:
        await asyncio.sleep(0)
        self.reads += 1
        if self.stop_after_reads is not None and self.reads >= self.stop_after_reads:
            self.stop_event.set()
        if self.reads <= self.failures:
            raise self.error
        return []


@dataclass
class _HangingReader:
    """A reader whose ``read`` suspends and never returns.

    Exists so a cancellation can be delivered *inside* ``consume_once``, which is
    the only place the loop's ``except`` clauses can see it. See
    ``test_tail_loop_propagates_cancellation``.
    """

    entered: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)
    cursor: str = "1788222000571-2"
    reads: int = 0

    def seek(self, message_id: str) -> None:
        self.cursor = message_id

    async def read(self, *, count: int, block_ms: int | None) -> list[Any]:
        self.reads += 1
        self.entered.set()
        # Releasable rather than permanent. A loop that ignores cancellation
        # cannot be killed, so without this the *failing* case would leave a task
        # pending forever on the session-scoped event loop and pytest would hang
        # at teardown instead of printing the failure.
        await self.release.wait()
        return []


@pytest.mark.asyncio
async def test_tail_does_not_advance_its_cursor_when_the_read_fails() -> None:
    """A broker error must not cost an entry, and the groupless tail has no PEL.

    This is the one loop where a dropped connection could *lose* data rather than
    merely delay it: ``info.watch-status`` is a groupless tail, so there is no
    pending list to reclaim from and the cursor is the only record of position.
    An advance past an entry that was never applied is a permanently missed
    status update, invisible except as a stale watched-item panel.

    Two things hold it. ``co_core_aio``'s reader assigns ``self._cursor`` only
    after a batch fully decodes, so a raising ``xread`` cannot advance it; and
    ``consume_once`` captures the pre-read cursor and rewinds on a handler
    failure. This asserts the loop preserves that from the outside, without
    reaching into co-core.
    """
    reader = _FlakyReader(failures=2, error=RedisConnectionError("broker gone"), stop_after_reads=4)
    before = reader.cursor

    await asyncio.wait_for(
        watch_status_consumer.run(
            session_factory=None,  # type: ignore[arg-type]
            reader=reader,  # type: ignore[arg-type]
            stop_event=reader.stop_event,
            error_backoff_base=_FAST_BACKOFF,
        ),
        timeout=10,
    )

    assert reader.reads == 4  # survived both failures
    assert reader.cursor == before, "a failed read moved the cursor - entries would be skipped"


@pytest.mark.asyncio
async def test_tail_loop_propagates_cancellation() -> None:
    """Shutdown must actually stop it.

    ``except Exception`` deliberately sits below ``except CancelledError``;
    swapping the order - or catching ``BaseException`` - yields a task that logs
    its own cancellation and loops forever, hanging the lifespan's ``await
    task``.

    **Asserts task state, not the exception** (CR round 4, finding 24 and what
    fixing it uncovered). The first version ended in
    ``pytest.raises(CancelledError): await task``, and a loop mutated to
    ``except BaseException`` - swallowing its own cancellation, the exact defect
    named above - still passed it in 0.02 s. The exception surfaced through
    ``await``/``wait_for`` plumbing whether or not the coroutine had honoured
    the cancel, so the assertion was about asyncio rather than about this loop.

    ``asyncio.wait`` is used instead of ``wait_for`` for that reason: it reports
    completion without re-raising, leaving ``task.cancelled()`` as a direct
    statement about the task.

    **And the cancel must land inside the read**, which is the part that took
    two attempts to get right. The loop's backoff -
    ``await asyncio.wait([...], timeout=delay)`` - sits *outside* the try, so a
    cancellation delivered there propagates no matter what the ``except``
    clauses do. Driving this with a fast backoff and an always-failing read put
    the cancel in the backoff essentially every time, so the mutated loop passed
    twice. ``_HangingReader`` suspends inside ``consume_once`` instead, which is
    the only await point those clauses actually guard.
    """
    reader = _HangingReader()
    stop_event = asyncio.Event()
    task = asyncio.create_task(
        watch_status_consumer.run(
            session_factory=None,  # type: ignore[arg-type]
            reader=reader,  # type: ignore[arg-type]
            stop_event=stop_event,
            error_backoff_base=_FAST_BACKOFF,
        )
    )

    # Bounded, for the reason ``_drive`` gives: the failure guarded against here
    # is "the task does not stop", and an unbounded wait expresses that as a hung
    # suite rather than a red test.
    try:
        await asyncio.wait_for(reader.entered.wait(), timeout=10)

        task.cancel()
        await asyncio.wait([task], timeout=10)

        assert task.done(), "the loop did not stop within 10s of being cancelled"
        assert task.cancelled(), "the loop swallowed its own cancellation"

        # And it stopped *working*, not merely stopped raising: a loop that ends
        # by some other route while still issuing reads would satisfy both above.
        reads_at_stop = reader.reads
        await asyncio.sleep(0.05)
        assert reader.reads == reads_at_stop, "the loop kept reading after cancellation"
    finally:
        # Unwedge the loop on the failing path. A regression here is a loop that
        # ignores cancellation, and nothing can kill such a task - so releasing
        # the read and setting the stop event is the only way to reclaim it. Skip
        # this and a red turns into a hung session loop, which reports nothing.
        reader.release.set()
        stop_event.set()
        await asyncio.wait([task], timeout=5)
