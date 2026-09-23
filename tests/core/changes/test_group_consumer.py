"""Tests for the shared consumer-group loop: naming (archiver#156) and the PEL walk (#259).

The delivery machinery in ``group_consumer`` is exercised end to end through the
two stream test files (``test_consumer``, ``test_artifacts_consumer``). What
lives here is what neither of those can assert.

The first is that a **restart** reuses its registration rather than minting a
new one, which a single test process cannot show because its pid never changes.

Before archiver#156 the consumer name carried the pid, so every restart that
received a message left a permanent orphan behind - seven registrations on the
production broker by 2026-08-27, six of them dead, none ever reaped. The name is
broker-visible (``XINFO CONSUMERS``), so it is a monitoring contract as much as
the group name is, and it is pinned here against silent drift.

The second is how the pending-list walks follow ``XAUTOCLAIM``'s cursor
(archiver#259). Those tests script ``claim_stale_page`` replies rather than
driving fakeredis, whose cursor is the highest *claimed* id - never the next id
to scan, never ``0-0``, and with no ``count * 10`` attempt budget. A walk tested
only there proves nothing about its end test.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch

import pytest
from co_core.effects.bus import BusMessage, ClaimPage, PoisonFrame
from co_core.pure.adapters.bus.envelope import from_wire, to_wire
from co_core.pure.adapters.bus.exceptions import BusMessageAnomaly
from co_core.pure.adapters.bus.streams import CONTENT_REVISIONS
from co_core.pure.models.changes import SourceRevisionObservedEvent
from fakeredis import aioredis as fakeredis_aio
from ulid import ULID

from src.core.changes import artifacts_consumer, group_consumer
from src.core.changes import consumer as revisions_consumer


@pytest.fixture
async def fake_redis():
    r = fakeredis_aio.FakeRedis()
    yield r
    await r.aclose()


def _observed() -> dict:
    """A decodable ``source_revision_observed`` frame; the payload is irrelevant here."""
    return to_wire(
        SourceRevisionObservedEvent(
            occurred_at=datetime.now(UTC),
            info_source_id=str(ULID()),
            extracted_fingerprint="sha256:" + "a" * 64,
            captured_at=datetime(2026, 8, 27, 12, 0, tzinfo=UTC),
            content_size_bytes=1024,
            content_media_type="text/plain",
            source_media_type="text/html",
            blob_uri="file:///var/lib/replicator/blobs/ab/cd/deadbeef.bin",
            command_id="cmd-naming",
        )
    )


def _as_text(value) -> str:
    return value.decode() if isinstance(value, bytes) else value


async def _consumer_names(fake_redis, topic: str, group: str) -> list[str]:
    return sorted(_as_text(c["name"]) for c in await fake_redis.xinfo_consumers(topic, group))


@pytest.mark.parametrize(
    ("group", "expected"),
    [
        (revisions_consumer.CONSUMER_GROUP, "archiver-revisions-1"),
        (artifacts_consumer.CONSUMER_GROUP, "archiver-artifacts-1"),
    ],
)
def test_consumer_name_is_derived_from_the_group(group: str, expected: str):
    assert group_consumer.resolve_consumer_name(group) == expected


def test_consumer_name_ignores_hostname_and_pid():
    """The two inputs that made it unstable, and the misattribution they caused.

    The VM's hostname is ``watcher`` (shared host), so a hostname-derived name
    read as Watcher's in ``XINFO`` output on a broker all three services share.
    """
    with patch("socket.gethostname", return_value="watcher"), patch("os.getpid", return_value=4242):
        first = group_consumer.resolve_consumer_name(revisions_consumer.CONSUMER_GROUP)
    with patch("socket.gethostname", return_value="elsewhere"), patch("os.getpid", return_value=7):
        second = group_consumer.resolve_consumer_name(revisions_consumer.CONSUMER_GROUP)

    assert first == second == "archiver-revisions-1"
    assert "watcher" not in first


@pytest.mark.parametrize(
    ("build", "group"),
    [
        (revisions_consumer.build_consumer, revisions_consumer.CONSUMER_GROUP),
        (artifacts_consumer.build_consumer, artifacts_consumer.CONSUMER_GROUP),
    ],
)
@pytest.mark.asyncio
async def test_build_consumer_defaults_to_the_derived_name(fake_redis, build, group):
    """Pins the derivation *path*, not just the helper - both modules re-export it."""
    assert build(fake_redis).name == group_consumer.resolve_consumer_name(group)


@pytest.mark.asyncio
async def test_restart_reuses_its_registration(fake_redis):
    """The regression this issue exists to prevent: one process, one registration.

    Each loop pass stands in for a service restart that received a message. With
    the pid in the name this left one orphan per pass, forever; with the name
    derived from the group each pass re-attaches to the first's registration.

    The ``os.getpid`` patch is inert against the current implementation, which
    reads neither pid nor hostname - it is here so that *reintroducing* a
    process-derived name fails this test rather than passing it. Without the
    patch it would pass either way, because the pid does not change within one
    test process, which is exactly why this case could not live in
    ``test_consumer``.
    """

    async def _settle(_message) -> bool:
        return True

    for pid in (100, 200, 300):
        await fake_redis.xadd(CONTENT_REVISIONS, _observed())
        with patch("os.getpid", return_value=pid):
            c = revisions_consumer.build_consumer(fake_redis)
        await revisions_consumer.ensure_group(c)
        assert await group_consumer.consume_once(consumer=c, handle=_settle) == 1

    names = await _consumer_names(fake_redis, CONTENT_REVISIONS, revisions_consumer.CONSUMER_GROUP)
    assert names == ["archiver-revisions-1"]


@pytest.mark.asyncio
async def test_startup_log_names_the_consumer(fake_redis):
    """The name must reach the journal, because ``XINFO`` may legitimately not show it.

    Registration happens on *delivery*, so a healthy consumer on a quiet stream is
    absent from ``XINFO CONSUMERS`` - the trap that made this issue take three
    rounds to close. ``deploy/README.md`` therefore directs an operator to verify
    a deploy from this line instead, which only works if the line carries the name.

    Asserted against the logger rather than ``caplog``: another test in the suite
    calls ``configure_logging()``, and the handler it installs stops propagation,
    so ``caplog`` captures this record when the module runs alone and not when the
    whole suite does.
    """
    stop_event = asyncio.Event()
    stop_event.set()
    c = revisions_consumer.build_consumer(fake_redis)

    with patch.object(group_consumer.logger, "info") as info:
        await group_consumer.run(consumer=c, handle=_never_called, stop_event=stop_event)

    starting = [call for call in info.call_args_list if call.args[0] == "Bus consumer starting"]
    assert len(starting) == 1
    assert starting[0].kwargs["extra"]["consumer"] == "archiver-revisions-1"


async def _never_called(_message) -> bool:  # pragma: no cover - the loop exits first
    raise AssertionError("stop_event was set; no message should be handled")


# --- The pending-list walks (archiver#259) ---------------------------------------


def _page(
    cursor: str,
    *,
    messages: tuple[BusMessage, ...] = (),
    poison: tuple[PoisonFrame, ...] = (),
    deleted: tuple[str, ...] = (),
) -> ClaimPage:
    return ClaimPage(messages=messages, poison=poison, cursor=cursor, deleted=deleted)


def _poison(message_id: str) -> PoisonFrame:
    fields = {"event_type": "not_a_real_event", "payload": "{}"}
    return PoisonFrame(
        message_id=message_id,
        fields=fields,
        anomaly=BusMessageAnomaly("undecodable", topic=CONTENT_REVISIONS, message_id=message_id),
    )


def _message(message_id: str) -> BusMessage:
    return from_wire(_observed(), topic=CONTENT_REVISIONS, message_id=message_id)


@dataclass
class _ScriptedBus:
    """An ``AsyncBusConsumer`` stand-in that serves scripted ``XAUTOCLAIM`` pages.

    ``pages`` is consumed in order; running out is a test failure, which is how
    a walk that fails to stop shows up. ``repeat`` instead serves one page
    forever, for the pass ceiling.
    """

    pages: list[ClaimPage] = field(default_factory=list)
    repeat: ClaimPage | None = None
    starts: list[str] = field(default_factory=list)
    min_idles: list[int] = field(default_factory=list)
    dead_lettered: list[str] = field(default_factory=list)
    acked: list[str] = field(default_factory=list)

    async def claim_stale_page(self, *, min_idle_ms: int, count: int, start_id: str) -> ClaimPage:
        self.starts.append(start_id)
        self.min_idles.append(min_idle_ms)
        if self.repeat is not None:
            return self.repeat
        assert self.pages, f"walk kept scanning past its last page (start_id={start_id})"
        return self.pages.pop(0)

    async def dead_letter(self, message_id: str, fields: dict[str, str]) -> str:
        self.dead_lettered.append(message_id)
        await self.ack(message_id)
        return f"dlq-{message_id}"

    async def ack(self, message_id: str) -> None:
        self.acked.append(message_id)


def _scripted(bus: Any) -> group_consumer.GroupConsumer:
    return group_consumer.GroupConsumer(
        bus=bus,
        name="archiver-revisions-1",
        topic=CONTENT_REVISIONS,
        group=revisions_consumer.CONSUMER_GROUP,
    )


async def _settle(_message: BusMessage) -> bool:
    return True


@pytest.mark.asyncio
async def test_quarantine_scan_keeps_going_past_an_empty_page_with_a_cursor():
    """An empty page is the ``count * 10`` attempt budget running out, not the end.

    The pre-#259 loop broke on ``not entries``, which would strand a poison frame
    behind a run of trimmed entries.
    """
    bus = _ScriptedBus(pages=[_page("5-0"), _page("0-0", poison=(_poison("6-0"),))])

    quarantined = await group_consumer.quarantine_undecodable(_scripted(bus))

    assert quarantined == 1
    assert bus.starts == ["0-0", "5-0"]
    assert bus.dead_lettered == ["6-0"]


@pytest.mark.asyncio
async def test_quarantine_scan_stops_when_the_page_is_exhausted():
    bus = _ScriptedBus(pages=[_page("0-0", poison=(_poison("1-0"),), messages=(_message("2-0"),))])

    assert await group_consumer.quarantine_undecodable(_scripted(bus)) == 1
    assert bus.starts == ["0-0"]
    assert bus.min_idles == [0]
    # Decodable entries stay pending for the next read or reclaim pass.
    assert bus.acked == ["1-0"]


@pytest.mark.asyncio
async def test_quarantine_scan_warns_at_its_pass_ceiling():
    bus = _ScriptedBus(repeat=_page("9-0"))

    with patch.object(group_consumer.logger, "warning") as warning:
        assert await group_consumer.quarantine_undecodable(_scripted(bus)) == 0

    assert len(bus.starts) == group_consumer.MAX_QUARANTINE_PASSES
    messages = [call.args[0] for call in warning.call_args_list]
    assert any("pass ceiling" in m for m in messages)


@pytest.mark.parametrize("walk", ["quarantine", "reclaim"])
@pytest.mark.asyncio
async def test_trimmed_pending_entries_are_logged(walk: str):
    """``page.deleted`` is the only record of pending work nobody processed."""
    bus = _ScriptedBus(pages=[_page("0-0", deleted=("1-0", "2-0"))])
    consumer = _scripted(bus)

    with patch.object(group_consumer.logger, "warning") as warning:
        if walk == "quarantine":
            await group_consumer.quarantine_undecodable(consumer)
        else:
            await group_consumer.reclaim_stale(consumer=consumer, handle=_settle)

    trimmed = [c for c in warning.call_args_list if "trimmed" in c.args[0]]
    assert len(trimmed) == 1
    extra = trimmed[0].kwargs["extra"]
    assert extra["count"] == 2
    assert extra["message_ids"] == ["1-0", "2-0"]
    assert extra["topic"] == CONTENT_REVISIONS


@pytest.mark.asyncio
async def test_trimmed_id_list_is_capped_in_the_log():
    many = tuple(f"{n}-0" for n in range(1, 51))
    bus = _ScriptedBus(pages=[_page("0-0", deleted=many)])

    with patch.object(group_consumer.logger, "warning") as warning:
        await group_consumer.quarantine_undecodable(_scripted(bus))

    extra = warning.call_args_list[0].kwargs["extra"]
    assert extra["count"] == 50
    assert extra["message_ids"] == list(many[: group_consumer.DELETED_LOG_IDS])


@pytest.mark.asyncio
async def test_reclaim_dead_letters_poison_and_processes_the_rest_in_one_pass():
    """Pre-#259 a bad frame in the page returned 0 and left its neighbours for later."""
    bus = _ScriptedBus(
        pages=[_page("0-0", messages=(_message("1-0"), _message("3-0")), poison=(_poison("2-0"),))]
    )
    handled: list[str] = []

    async def _handle(message: BusMessage) -> bool:
        handled.append(message.message_id)
        return True

    settled = await group_consumer.reclaim_stale(consumer=_scripted(bus), handle=_handle)

    assert settled == 3
    assert bus.dead_lettered == ["2-0"]
    assert handled == ["1-0", "3-0"]
    assert sorted(bus.acked) == ["1-0", "2-0", "3-0"]


@pytest.mark.asyncio
async def test_reclaim_reads_one_page_and_advances_the_cursor():
    """replicator#102's shape: restarting at ``0-0`` every pass lets the first
    ``CLAIM_COUNT`` slow failures take every turn."""
    bus = _ScriptedBus(pages=[_page("7-0"), _page("0-0"), _page("4-0")])
    consumer = _scripted(bus)
    cursor = group_consumer.ReclaimCursor()

    await group_consumer.reclaim_stale(consumer=consumer, handle=_settle, cursor=cursor)
    assert cursor.position == "7-0"
    await group_consumer.reclaim_stale(consumer=consumer, handle=_settle, cursor=cursor)
    assert cursor.position == "0-0"  # exhausted: the next pass wraps
    await group_consumer.reclaim_stale(consumer=consumer, handle=_settle, cursor=cursor)

    assert bus.starts == ["0-0", "7-0", "0-0"]


@dataclass
class _LoopBus(_ScriptedBus):
    """Drives ``run``: ``read`` yields, fails on the listed reads, and stops the loop."""

    fail_reads: frozenset[int] = frozenset()
    stop_after_reads: int = 1
    stop_event: asyncio.Event = field(default_factory=asyncio.Event)
    reads: int = 0

    async def ensure_group(self, *, start_id: str) -> None:
        return None

    async def read(self, *, count: int, block_ms: int | None) -> list[BusMessage]:
        await asyncio.sleep(0)
        self.reads += 1
        if self.reads >= self.stop_after_reads:
            self.stop_event.set()
        if self.reads in self.fail_reads:
            raise ConnectionError("broker went away")
        return []

    async def claim_stale_page(self, *, min_idle_ms: int, count: int, start_id: str) -> ClaimPage:
        self.starts.append(start_id)
        return _page(f"{len(self.starts)}-0")


@pytest.mark.asyncio
async def test_run_carries_the_reclaim_cursor_across_passes_and_resets_it_on_failure():
    """A loop failure re-arms the group; a flush destroys it, and the cursor with it."""
    bus = _LoopBus(fail_reads=frozenset({3}), stop_after_reads=4)

    await asyncio.wait_for(
        group_consumer.run(
            consumer=_scripted(bus),
            handle=_settle,
            stop_event=bus.stop_event,
            claim_interval_iterations=1,
            error_backoff_base=0.001,
        ),
        timeout=10,
    )

    assert bus.starts == ["0-0", "1-0", "0-0"]
