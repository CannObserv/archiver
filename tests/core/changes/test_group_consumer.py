"""Tests for the shared consumer-group loop's naming contract (archiver#156).

The delivery machinery in ``group_consumer`` is exercised end to end through the
two stream test files (``test_consumer``, ``test_artifacts_consumer``). What
lives here is the one property neither of those can assert, because within a
single test process the pid never changes: that a **restart** reuses its
registration rather than minting a new one.

Before archiver#156 the consumer name carried the pid, so every restart that
received a message left a permanent orphan behind - seven registrations on the
production broker by 2026-08-27, six of them dead, none ever reaped. The name is
broker-visible (``XINFO CONSUMERS``), so it is a monitoring contract as much as
the group name is, and it is pinned here against silent drift.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from co_core.pure.adapters.bus.envelope import to_wire
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
