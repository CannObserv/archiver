"""Tests for the ``info.watch-status`` tail consumer (archiver#151).

The loop half: groupless replay-then-tail, persisted resume cursor, no-DLQ
poison handling. The apply semantics themselves are covered in
``tests/core/services/test_watch_status.py``.

Covers:
1. A published status lands in the cache and the cursor advances
2. Restart resumes from the persisted cursor — earlier entries are not re-read
3. Cold start (no cursor row) replays from 0-0
4. An undecodable frame is logged, skipped, and the skip is persisted
5. Another event type on the stream is skipped-but-advanced
6. A DB failure rewinds the reader — the message is redelivered, not lost
7. The loop honours stop_event and cancels cleanly
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from co_core.pure.adapters.bus.envelope import to_wire
from co_core.pure.models.changes import SourceRevisionObservedEvent, WatchStatusState
from fakeredis import aioredis as fakeredis_aio
from sqlalchemy import delete, select
from sqlalchemy.exc import DataError, OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.core.changes import watch_status_consumer
from src.core.models import BusTailCursor, InfoItem, WatchStatus
from src.core.services.watch_status import WATCH_STATUS_TOPIC, read_cursor

OCCURRED_AT = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


@pytest.fixture
async def fake_redis():
    r = fakeredis_aio.FakeRedis()
    yield r
    await r.aclose()


@pytest.fixture
def session_factory(test_engine):
    return async_sessionmaker(bind=test_engine, expire_on_commit=False)


@pytest.fixture
async def item(session_factory):
    async with session_factory() as s:
        item = InfoItem(name="Tail target")
        s.add(item)
        await s.commit()
        yield item
        # Cleanup — session_factory writes are real commits, not savepoints.
        fresh = await s.get(InfoItem, item.info_item_id)
        if fresh is not None:
            await s.delete(fresh)
            await s.commit()


async def _cleanup_cursor(session_factory):
    async with session_factory() as s:
        await s.execute(delete(BusTailCursor))
        await s.commit()


def _status(item_id: str, generation: int = 1) -> dict[str, str]:
    return to_wire(
        WatchStatusState(
            occurred_at=OCCURRED_AT,
            info_item_id=item_id,
            applied_generation=generation,
            applied_active=True,
            health="ok",
        )
    )


async def _get_row(session_factory, item_id):
    async with session_factory() as s:
        return (
            await s.execute(select(WatchStatus).where(WatchStatus.info_item_id == item_id))
        ).scalar_one_or_none()


async def test_status_applied_and_cursor_advanced(fake_redis, session_factory, item):
    try:
        entry_id = await fake_redis.xadd(WATCH_STATUS_TOPIC, _status(str(item.info_item_id)))
        reader = watch_status_consumer.build_reader(fake_redis)

        applied = await watch_status_consumer.consume_once(
            session_factory=session_factory, reader=reader
        )

        assert applied == 1
        row = await _get_row(session_factory, item.info_item_id)
        assert row is not None
        assert row.applied_generation == 1
        async with session_factory() as s:
            assert await read_cursor(s, WATCH_STATUS_TOPIC) == entry_id.decode()
    finally:
        await _cleanup_cursor(session_factory)


async def test_restart_resumes_from_persisted_cursor(fake_redis, session_factory, item):
    try:
        await fake_redis.xadd(WATCH_STATUS_TOPIC, _status(str(item.info_item_id), generation=1))
        reader = watch_status_consumer.build_reader(fake_redis)
        await watch_status_consumer.consume_once(session_factory=session_factory, reader=reader)

        # Second message, then a "restart": a fresh reader from the persisted cursor.
        await fake_redis.xadd(WATCH_STATUS_TOPIC, _status(str(item.info_item_id), generation=2))
        start_id = await watch_status_consumer.resolve_start_id(session_factory)
        assert start_id != "0-0"
        fresh = watch_status_consumer.build_reader(fake_redis, start_id=start_id)

        applied = await watch_status_consumer.consume_once(
            session_factory=session_factory, reader=fresh
        )
        assert applied == 1  # only the delta, not a replay of both
        row = await _get_row(session_factory, item.info_item_id)
        assert row.applied_generation == 2
    finally:
        await _cleanup_cursor(session_factory)


async def test_cold_start_replays_from_zero(session_factory):
    assert await watch_status_consumer.resolve_start_id(session_factory) == "0-0"


async def test_poison_frame_skipped_and_skip_persisted(fake_redis, session_factory, item):
    try:
        poison_id = await fake_redis.xadd(
            WATCH_STATUS_TOPIC, {"event_type": "watch_status", "payload": "not json"}
        )
        good_id = await fake_redis.xadd(WATCH_STATUS_TOPIC, _status(str(item.info_item_id)))
        reader = watch_status_consumer.build_reader(fake_redis)

        assert (
            await watch_status_consumer.consume_once(session_factory=session_factory, reader=reader)
            == 0
        )
        async with session_factory() as s:
            assert await read_cursor(s, WATCH_STATUS_TOPIC) == poison_id.decode()

        assert (
            await watch_status_consumer.consume_once(session_factory=session_factory, reader=reader)
            == 1
        )
        assert (await _get_row(session_factory, item.info_item_id)) is not None
        async with session_factory() as s:
            assert await read_cursor(s, WATCH_STATUS_TOPIC) == good_id.decode()
    finally:
        await _cleanup_cursor(session_factory)


async def test_other_event_type_skipped_but_advanced(fake_redis, session_factory, item):
    try:
        frame = to_wire(
            SourceRevisionObservedEvent(
                occurred_at=OCCURRED_AT,
                info_source_id="01K2E0AAAAAAAAAAAAAAAAAAAA",
                extracted_fingerprint="sha256:" + "a" * 64,
                captured_at=OCCURRED_AT,
                command_id="cmd-1",
                blob_uri="file:///var/lib/replicator/blobs/aa/bb/cafe.bin",
                spec_fingerprint="spec1:sha256:" + "e" * 64,
                content_size_bytes=1024,
                content_media_type="text/html",
                source_media_type="text/html",
            )
        )
        entry_id = await fake_redis.xadd(WATCH_STATUS_TOPIC, frame)
        reader = watch_status_consumer.build_reader(fake_redis)

        applied = await watch_status_consumer.consume_once(
            session_factory=session_factory, reader=reader
        )
        assert applied == 1  # settled, though nothing was cached
        assert (await _get_row(session_factory, item.info_item_id)) is None
        async with session_factory() as s:
            assert await read_cursor(s, WATCH_STATUS_TOPIC) == entry_id.decode()
    finally:
        await _cleanup_cursor(session_factory)


async def test_db_failure_rewinds_reader(fake_redis, session_factory, item):
    try:
        await fake_redis.xadd(WATCH_STATUS_TOPIC, _status(str(item.info_item_id)))
        reader = watch_status_consumer.build_reader(fake_redis)

        with (
            patch.object(
                watch_status_consumer,
                "apply_watch_status",
                side_effect=RuntimeError("db down"),
            ),
            pytest.raises(RuntimeError),
        ):
            await watch_status_consumer.consume_once(session_factory=session_factory, reader=reader)

        # Nothing persisted, and the reader rewound: the retry delivers it.
        assert (await _get_row(session_factory, item.info_item_id)) is None
        applied = await watch_status_consumer.consume_once(
            session_factory=session_factory, reader=reader
        )
        assert applied == 1
        assert (await _get_row(session_factory, item.info_item_id)) is not None
    finally:
        await _cleanup_cursor(session_factory)


async def test_run_stops_on_cancel(fake_redis, session_factory):
    stop_event = asyncio.Event()
    reader = watch_status_consumer.build_reader(fake_redis)
    task = asyncio.create_task(
        watch_status_consumer.run(
            session_factory=session_factory,
            reader=reader,
            stop_event=stop_event,
            block_ms=10,
        )
    )
    await asyncio.sleep(0.05)
    assert not task.done()
    stop_event.set()
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def test_terminal_apply_error_is_skipped_not_retried_forever(
    fake_redis, session_factory, item
):
    """A message the registry can *never* apply must not wedge the tail.

    With no DLQ on this stream kind and a cursor that only advances on a
    successful apply, an un-appliable message would otherwise be retried
    forever — a silent total stall of the very stream that exists to detect
    silent drift. The skip is the disposition; the LWW republish is the repair.
    """
    entry_id = await fake_redis.xadd(WATCH_STATUS_TOPIC, _status(str(item.info_item_id)))
    reader = watch_status_consumer.build_reader(fake_redis)

    try:
        with patch.object(
            watch_status_consumer,
            "apply_watch_status",
            side_effect=DataError("stmt", {}, Exception("value too long for type")),
        ):
            applied = await watch_status_consumer.consume_once(
                session_factory=session_factory, reader=reader
            )

        assert applied == 0
        # The skip is durable: a restart must not re-hit the same frame.
        async with session_factory() as s:
            assert await read_cursor(s, WATCH_STATUS_TOPIC) == entry_id.decode()
        assert reader.cursor == entry_id.decode()
    finally:
        await _cleanup_cursor(session_factory)


async def test_transient_apply_error_still_rewinds_for_redelivery(
    fake_redis, session_factory, item
):
    """The counterpart: a failure redelivery *can* resolve must never be skipped."""
    await fake_redis.xadd(WATCH_STATUS_TOPIC, _status(str(item.info_item_id)))
    reader = watch_status_consumer.build_reader(fake_redis)

    try:
        with (
            patch.object(
                watch_status_consumer,
                "apply_watch_status",
                side_effect=OperationalError("stmt", {}, Exception("connection lost")),
            ),
            pytest.raises(OperationalError),
        ):
            await watch_status_consumer.consume_once(session_factory=session_factory, reader=reader)

        # Nothing persisted, reader rewound — the next pass redelivers it.
        async with session_factory() as s:
            assert await read_cursor(s, WATCH_STATUS_TOPIC) is None
        assert (
            await watch_status_consumer.consume_once(session_factory=session_factory, reader=reader)
            == 1
        )
    finally:
        await _cleanup_cursor(session_factory)


async def test_open_vocabulary_health_token_applies(fake_redis, session_factory, item):
    """`health` is an unconstrained str on the wire and the vocabulary is
    expected to grow; a long token must persist, not wedge the consumer."""
    long_health = "degraded-" + "x" * 200
    frame = to_wire(
        WatchStatusState(
            occurred_at=OCCURRED_AT,
            info_item_id=str(item.info_item_id),
            applied_generation=1,
            applied_active=True,
            health=long_health,
        )
    )
    try:
        await fake_redis.xadd(WATCH_STATUS_TOPIC, frame)
        reader = watch_status_consumer.build_reader(fake_redis)

        assert (
            await watch_status_consumer.consume_once(session_factory=session_factory, reader=reader)
            == 1
        )
        row = await _get_row(session_factory, item.info_item_id)
        assert row.health == long_health
    finally:
        await _cleanup_cursor(session_factory)


async def test_consecutive_skips_are_counted_and_throttled(fake_redis, session_factory, item):
    """A stuck producer must not write one ERROR per message forever.

    The count is carried across `consume_once` calls (that is what makes it
    *consecutive*), mirrors the loop's own ERROR_LOG_EVERY escalation, and
    resets the moment a message applies cleanly.
    """
    throttle = watch_status_consumer.SkipThrottle()
    try:
        for _ in range(watch_status_consumer.ERROR_LOG_EVERY + 1):
            await fake_redis.xadd(WATCH_STATUS_TOPIC, _status(str(item.info_item_id)))
        reader = watch_status_consumer.build_reader(fake_redis)

        with patch.object(
            watch_status_consumer,
            "apply_watch_status",
            side_effect=DataError("stmt", {}, Exception("nope")),
        ):
            for _ in range(watch_status_consumer.ERROR_LOG_EVERY + 1):
                await watch_status_consumer.consume_once(
                    session_factory=session_factory, reader=reader, skip_throttle=throttle
                )

        assert throttle.consecutive == watch_status_consumer.ERROR_LOG_EVERY + 1

        # A clean apply resets the run — the next fault is loud again.
        await fake_redis.xadd(WATCH_STATUS_TOPIC, _status(str(item.info_item_id)))
        await watch_status_consumer.consume_once(
            session_factory=session_factory, reader=reader, skip_throttle=throttle
        )
        assert throttle.consecutive == 0
    finally:
        await _cleanup_cursor(session_factory)


def test_skip_throttle_logs_first_then_every_nth():
    throttle = watch_status_consumer.SkipThrottle()
    every = watch_status_consumer.ERROR_LOG_EVERY
    emitted = [i for i in range(1, every * 2 + 1) if throttle.record()]
    assert emitted[0] == 1
    assert watch_status_consumer.ERROR_LOG_EVERY in emitted
    assert len(emitted) < watch_status_consumer.ERROR_LOG_EVERY  # suppression happened
