"""Tests for the ``content.revisions`` ingest consumer (archiver#139).

Archiver's first *consumer* role on the bus — it has only ever produced. The
consumer reads ``SourceRevisionObservedEvent`` facts, decides what the registry
records, and lets the existing outbox emit ``source_revision_captured`` on
``info.changes`` with unchanged semantics for existing subscribers.

Covers, per-message:
1. A new observation → row written, one outbox event, message acked
2. Redelivery of the same key → no second row, no second outbox event
3. Unknown info_source_id → ack and drop, nothing written
4. Fingerprint not in the sha256:<64 hex> spelling → quarantined, nothing written
5. Every wire field lands on its column, blob_* included
6. A DB failure leaves the message un-acked (redelivery, not loss)

And, around the loop:
7. The group is created at "0" so entries predating it are still consumed
8. A poison frame is DLQ'd and acked rather than wedging the loop
9. Stale pending entries from a dead consumer are reclaimed
10. The gate: no ARCHIVER_BUS_CONSUMER, no consumer
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import Mock

import pytest
from co_core.pure.adapters.bus.envelope import to_wire
from co_core.pure.adapters.bus.streams import CONTENT_REVISIONS
from co_core.pure.models.changes import SourceRevisionObservedEvent
from co_core_aio.bus import AsyncBusConsumer
from fakeredis import aioredis as fakeredis_aio
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker
from ulid import ULID

from src.core.changes import consumer as revisions_consumer
from src.core.models import ChangesOutboxRow, InfoSource, SourceRevision

pytestmark = pytest.mark.integration

FP_OBSERVED = "sha256:" + "a" * 64
CAPTURED_AT = datetime(2026, 8, 9, 11, 0, tzinfo=UTC)
BLOB_EXPIRES_AT = datetime(2026, 8, 16, 11, 0, tzinfo=UTC)


@pytest.fixture
async def fake_redis():
    r = fakeredis_aio.FakeRedis()
    yield r
    await r.aclose()


@pytest.fixture
def session_factory(test_engine):
    return async_sessionmaker(bind=test_engine, expire_on_commit=False)


@pytest.fixture(autouse=True)
async def clean_tables(test_engine):
    """These tests commit for real (ack-after-commit is the thing under test)."""
    async with test_engine.begin() as conn:
        await conn.execute(text("TRUNCATE TABLE information.changes_outbox"))
        await conn.execute(text("TRUNCATE TABLE information.source_revisions CASCADE"))
    yield
    async with test_engine.begin() as conn:
        await conn.execute(text("TRUNCATE TABLE information.changes_outbox"))
        await conn.execute(text("TRUNCATE TABLE information.source_revisions CASCADE"))


@pytest.fixture
async def info_source(session_factory) -> InfoSource:
    """A committed InfoSource — the consumer opens its own session."""
    async with session_factory() as s:
        src = InfoSource(
            url="https://example.com/consumer-test",
            source_specs=[
                {"schema_version": 1, "extraction": {"algorithm": "full_page"}, "fingerprint": {}}
            ],
        )
        s.add(src)
        await s.commit()
        return src


def _observed(info_source_id, fingerprint: str = FP_OBSERVED, **overrides) -> dict:
    """A full ``source_revision_observed`` wire payload."""
    event = SourceRevisionObservedEvent(
        occurred_at=datetime.now(UTC),
        info_source_id=str(info_source_id),
        extracted_fingerprint=fingerprint,
        captured_at=CAPTURED_AT,
        content_size_bytes=2048,
        content_media_type="text/plain",
        source_media_type="text/html",
        blob_uri="file:///var/lib/replicator/blobs/ab/cd/deadbeef.bin",
        command_id="cmd-observed",
        spec_fingerprint="sha256:" + "e" * 64,
        **{"blob_expires_at": BLOB_EXPIRES_AT, **overrides},
    )
    return to_wire(event)


async def _bus_consumer(fake_redis, name: str = "test:1"):
    c = revisions_consumer.build_consumer(fake_redis, consumer_name=name)
    await revisions_consumer.ensure_group(c)
    return c


async def _row_count(session_factory, model) -> int:
    async with session_factory() as s:
        result = await s.execute(select(func.count()).select_from(model))
        return result.scalar_one()


async def _pending_count(fake_redis) -> int:
    summary = await fake_redis.xpending(CONTENT_REVISIONS, revisions_consumer.CONSUMER_GROUP)
    return summary["pending"]


@pytest.mark.asyncio
async def test_observation_writes_row_outbox_and_acks(session_factory, fake_redis, info_source):
    await fake_redis.xadd(CONTENT_REVISIONS, _observed(info_source.info_source_id))
    consumer = await _bus_consumer(fake_redis)

    processed = await revisions_consumer.consume_once(
        session_factory=session_factory, consumer=consumer
    )

    assert processed == 1
    async with session_factory() as s:
        row = (await s.execute(select(SourceRevision))).scalar_one()
        outbox = (await s.execute(select(ChangesOutboxRow))).scalar_one()
    assert row.content_fingerprint == FP_OBSERVED
    assert outbox.topic == "info.changes"
    assert outbox.payload["event_type"] == "source_revision_captured"
    assert outbox.payload["source_revision_id"] == str(row.source_revision_id)
    # Acked only after the commit — nothing left pending in the group.
    assert await _pending_count(fake_redis) == 0


@pytest.mark.asyncio
async def test_archiver_allocates_the_revision_id(session_factory, fake_redis, info_source):
    """The wire carries no source_revision_id; the registry mints it (cannobserv#301)."""
    await fake_redis.xadd(CONTENT_REVISIONS, _observed(info_source.info_source_id))
    consumer = await _bus_consumer(fake_redis)

    await revisions_consumer.consume_once(session_factory=session_factory, consumer=consumer)

    async with session_factory() as s:
        row = (await s.execute(select(SourceRevision))).scalar_one()
    assert isinstance(row.source_revision_id, ULID)


@pytest.mark.asyncio
async def test_redelivery_is_a_no_op(session_factory, fake_redis, info_source):
    """At-least-once redelivery writes no duplicate row and no duplicate event."""
    frame = _observed(info_source.info_source_id)
    await fake_redis.xadd(CONTENT_REVISIONS, frame)
    await fake_redis.xadd(CONTENT_REVISIONS, frame)
    consumer = await _bus_consumer(fake_redis)

    await revisions_consumer.consume_once(session_factory=session_factory, consumer=consumer)
    await revisions_consumer.consume_once(session_factory=session_factory, consumer=consumer)

    assert await _row_count(session_factory, SourceRevision) == 1
    assert await _row_count(session_factory, ChangesOutboxRow) == 1
    assert await _pending_count(fake_redis) == 0


@pytest.mark.asyncio
async def test_unknown_info_source_is_acked_and_dropped(session_factory, fake_redis):
    """The registry is the authority on what exists (archiver#139)."""
    await fake_redis.xadd(CONTENT_REVISIONS, _observed(ULID()))
    consumer = await _bus_consumer(fake_redis)

    processed = await revisions_consumer.consume_once(
        session_factory=session_factory, consumer=consumer
    )

    assert processed == 1
    assert await _row_count(session_factory, SourceRevision) == 0
    assert await _row_count(session_factory, ChangesOutboxRow) == 0
    assert await _pending_count(fake_redis) == 0
    # Dropped, not quarantined — a fact about something we do not hold is not poison.
    assert await fake_redis.xlen(f"{CONTENT_REVISIONS}.dlq") == 0


@pytest.mark.asyncio
async def test_misspelled_fingerprint_is_quarantined(session_factory, fake_redis, info_source):
    """A fingerprint outside sha256:<64 hex> would write an unmatchable row.

    Archiver's uniqueness key is (info_source_id, content_fingerprint); a
    differently-spelled fingerprint for identical content is a silent duplicate,
    so this is loud rather than stored.
    """
    await fake_redis.xadd(
        CONTENT_REVISIONS, _observed(info_source.info_source_id, fingerprint="deadbeef")
    )
    consumer = await _bus_consumer(fake_redis)

    await revisions_consumer.consume_once(session_factory=session_factory, consumer=consumer)

    assert await _row_count(session_factory, SourceRevision) == 0
    assert await fake_redis.xlen(f"{CONTENT_REVISIONS}.dlq") == 1
    assert await _pending_count(fake_redis) == 0


@pytest.mark.asyncio
async def test_every_wire_field_lands_on_its_column(session_factory, fake_redis, info_source):
    await fake_redis.xadd(CONTENT_REVISIONS, _observed(info_source.info_source_id))
    consumer = await _bus_consumer(fake_redis)

    await revisions_consumer.consume_once(session_factory=session_factory, consumer=consumer)

    async with session_factory() as s:
        row = (await s.execute(select(SourceRevision))).scalar_one()
    assert row.info_source_id == info_source.info_source_id
    assert row.content_fingerprint == FP_OBSERVED
    assert row.captured_at == CAPTURED_AT
    assert row.content_size_bytes == 2048
    assert row.content_media_type == "text/plain"
    assert row.source_media_type == "text/html"
    assert row.command_id == "cmd-observed"
    assert row.spec_fingerprint == "sha256:" + "e" * 64
    # The blob is a cache, not durable storage — hence the content_cache_* names.
    assert row.content_cache_uri == "file:///var/lib/replicator/blobs/ab/cd/deadbeef.bin"
    assert row.content_cache_expires_at == BLOB_EXPIRES_AT


@pytest.mark.asyncio
async def test_absent_blob_expiry_records_absence(session_factory, fake_redis, info_source):
    """``None`` means the horizon is unknown — never substitute a guessed TTL."""
    await fake_redis.xadd(
        CONTENT_REVISIONS, _observed(info_source.info_source_id, blob_expires_at=None)
    )
    consumer = await _bus_consumer(fake_redis)

    await revisions_consumer.consume_once(session_factory=session_factory, consumer=consumer)

    async with session_factory() as s:
        row = (await s.execute(select(SourceRevision))).scalar_one()
    assert row.content_cache_expires_at is None


@pytest.mark.asyncio
async def test_database_failure_leaves_the_message_pending(fake_redis, info_source):
    """Redelivery, not loss: no ack when the write did not commit."""
    await fake_redis.xadd(CONTENT_REVISIONS, _observed(info_source.info_source_id))
    consumer = await _bus_consumer(fake_redis)
    # session_factory is called synchronously, so a plain Mock raises in-place.
    exploding = Mock(side_effect=RuntimeError("database is on fire"))

    processed = await revisions_consumer.consume_once(session_factory=exploding, consumer=consumer)

    assert processed == 0
    assert await _pending_count(fake_redis) == 1
    assert await fake_redis.xlen(f"{CONTENT_REVISIONS}.dlq") == 0


@pytest.mark.asyncio
async def test_group_starts_at_zero_so_earlier_entries_are_consumed(
    session_factory, fake_redis, info_source
):
    """``$`` would drop everything published before the group first existed."""
    await fake_redis.xadd(CONTENT_REVISIONS, _observed(info_source.info_source_id))

    consumer = revisions_consumer.build_consumer(fake_redis, consumer_name="test:2")
    await revisions_consumer.ensure_group(consumer)
    processed = await revisions_consumer.consume_once(
        session_factory=session_factory, consumer=consumer
    )

    assert processed == 1
    assert await _row_count(session_factory, SourceRevision) == 1


@pytest.mark.asyncio
async def test_poison_frame_is_dlqd_not_wedged(session_factory, fake_redis, info_source):
    """A frame that will not decode must not spin forever.

    ``AsyncBusConsumer.read`` raises inside the call, before returning any
    message id, so there is nothing to hand ``dead_letter`` — the recovery pass
    goes back to the raw PEL to find it.
    """
    await fake_redis.xadd(CONTENT_REVISIONS, {"event_type": "not_a_real_event", "payload": "{}"})
    await fake_redis.xadd(CONTENT_REVISIONS, _observed(info_source.info_source_id))
    consumer = await _bus_consumer(fake_redis)

    # First pass hits the poison and quarantines it; the second gets the good one.
    await revisions_consumer.consume_once(session_factory=session_factory, consumer=consumer)
    await revisions_consumer.consume_once(session_factory=session_factory, consumer=consumer)

    assert await fake_redis.xlen(f"{CONTENT_REVISIONS}.dlq") == 1
    assert await _row_count(session_factory, SourceRevision) == 1
    assert await _pending_count(fake_redis) == 0


@pytest.mark.asyncio
async def test_stale_pending_entries_are_reclaimed(session_factory, fake_redis, info_source):
    """A consumer that died mid-message must not park it in the PEL forever."""
    await fake_redis.xadd(CONTENT_REVISIONS, _observed(info_source.info_source_id))
    dead = AsyncBusConsumer(
        fake_redis,
        topic=CONTENT_REVISIONS,
        group=revisions_consumer.CONSUMER_GROUP,
        consumer="dead:1",
    )
    await dead.ensure_group(start_id="0")
    await dead.read(count=1)  # read but never acked
    assert await _pending_count(fake_redis) == 1

    live = revisions_consumer.build_consumer(fake_redis, consumer_name="live:1")
    reclaimed = await revisions_consumer.reclaim_stale(
        session_factory=session_factory, consumer=live, min_idle_ms=0
    )

    assert reclaimed == 1
    assert await _row_count(session_factory, SourceRevision) == 1
    assert await _pending_count(fake_redis) == 0


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, False), ("", False), ("0", False), ("no", False), ("1", True), ("true", True)],
)
def test_consumer_gate(value, expected):
    """Presence of a Redis URL is not authority to join a production group.

    Any process sourcing /etc/archiver/.env inherits ARCHIVER_REDIS_URL; a
    competing consumer in the group silently swallows revisions into whatever
    database it happens to hold. Only deploy/archiver.service sets the gate.
    """
    assert revisions_consumer.consumer_enabled(value) is expected
