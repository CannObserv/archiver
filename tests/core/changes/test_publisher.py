"""Tests for src/core/changes/publisher — outbox drain → co-core bus driver.

The drain loop reconstructs each stored outbox payload into its typed co-core
model and publishes it through ``AsyncBusPublisher`` (a ``BusPublish`` XADD),
building the wire envelope with ``co_core.pure.adapters.bus.envelope.to_wire``.
These tests assert on the canonical envelope field set (``key`` / ``payload`` /
``event_type`` / ``schema_version`` / ``occurred_at`` / ``content_type``).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from co_core_aio.bus import AsyncBusPublisher
from fakeredis import aioredis as fakeredis_aio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.core.changes.publisher import drain_once
from src.core.models import ChangesOutboxRow

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def fake_redis():
    """Provide an in-process FakeRedis async client with stream support."""
    client = fakeredis_aio.FakeRedis()
    yield client
    await client.aclose()


@pytest.fixture
def publisher(fake_redis):
    """The co-core bus driver bound to the fake Redis client."""
    return AsyncBusPublisher(fake_redis)


@pytest.fixture
async def session_factory(test_engine):
    """Return a real async_sessionmaker bound to the test engine.

    Unlike the shared ``session`` fixture (which wraps everything in a
    SAVEPOINT), this factory creates independent sessions so that
    ``drain_once`` can open and commit its own session — matching production
    behaviour.
    """
    return async_sessionmaker(bind=test_engine, expire_on_commit=False)


@pytest.fixture(autouse=True)
async def cleanup_outbox(test_engine):
    """Truncate the outbox table before and after each test."""
    async with test_engine.begin() as conn:
        await conn.execute(text("TRUNCATE TABLE information.changes_outbox"))
    yield
    async with test_engine.begin() as conn:
        await conn.execute(text("TRUNCATE TABLE information.changes_outbox"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _captured_event(source_revision_id: str = "rev-1") -> dict:
    """A full ``source_revision_captured`` payload as stored in the outbox.

    Matches ``model_dump(mode="json")`` of the co-core event the route emits.
    """
    return {
        "schema_version": 2,
        "event_type": "source_revision_captured",
        "occurred_at": "2026-07-28T12:00:00+00:00",
        "info_source_id": "01HZZ000000000000000000001",
        "source_revision_id": source_revision_id,
        "content_fingerprint": "sha256:" + "a" * 64,
        "bindings": [{"info_item_id": "01HZZ000000000000000000003"}],
    }


def _primary_changed_event(info_item_id: str, new_info_source_id: str) -> dict:
    """A full ``info_item_primary_changed`` payload as stored in the outbox."""
    return {
        "schema_version": 1,
        "event_type": "info_item_primary_changed",
        "occurred_at": "2026-07-28T12:00:00+00:00",
        "info_item_id": info_item_id,
        "old_info_source_id": None,
        "new_info_source_id": new_info_source_id,
    }


async def _insert_row(
    session_factory: async_sessionmaker,
    topic: str = "info.changes",
    payload: dict | None = None,
    published_at: datetime | None = None,
) -> ChangesOutboxRow:
    """Insert one ChangesOutboxRow and return it (refreshed)."""
    row = ChangesOutboxRow(
        topic=topic,
        payload=payload or _captured_event(),
        published_at=published_at,
    )
    async with session_factory() as s:
        s.add(row)
        await s.commit()
        await s.refresh(row)
    return row


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_drain_empty(session_factory, publisher, fake_redis):
    """Empty outbox → drain returns 0, no XADD calls."""
    n = await drain_once(session_factory=session_factory, publisher=publisher)
    assert n == 0
    keys = await fake_redis.keys("*")
    assert keys == []


@pytest.mark.asyncio
async def test_drain_single_row_writes_canonical_envelope(session_factory, publisher, fake_redis):
    """Single row drains: one XADD with the full co-core envelope; row updated."""
    row = await _insert_row(session_factory, payload=_captured_event("rev-42"))

    n = await drain_once(session_factory=session_factory, publisher=publisher)
    assert n == 1

    messages = await fake_redis.xrange("info.changes")
    assert len(messages) == 1
    _msg_id, fields = messages[0]

    # Idempotency key derived from source_revision_id.
    assert fields[b"key"] == b"rev-42"
    # Hoisted top-level envelope fields.
    assert fields[b"event_type"] == b"source_revision_captured"
    assert fields[b"schema_version"] == b"2"
    assert fields[b"occurred_at"] == b"2026-07-28T12:00:00+00:00"
    assert fields[b"content_type"] == b"application/json"
    # Self-describing JSON payload.
    parsed = json.loads(fields[b"payload"])
    assert parsed["source_revision_id"] == "rev-42"
    assert parsed["event_type"] == "source_revision_captured"

    async with session_factory() as s:
        refreshed = await s.get(ChangesOutboxRow, row.id)
    assert refreshed is not None
    assert refreshed.published_at is not None
    assert refreshed.bus_message_id is not None
    assert refreshed.publish_attempts == 0  # success path doesn't increment failure counter
    assert refreshed.last_error is None


@pytest.mark.asyncio
async def test_primary_changed_key_is_composite(session_factory, publisher, fake_redis):
    """info_item_primary_changed derives the composite idempotency key.

    (The old hand-rolled publisher keyed every event on ``source_revision_id``,
    yielding an empty key for this type — co-core's ``idempotency_key`` fixes it.)
    """
    await _insert_row(
        session_factory,
        payload=_primary_changed_event(info_item_id="item-1", new_info_source_id="src-9"),
    )

    n = await drain_once(session_factory=session_factory, publisher=publisher)
    assert n == 1

    messages = await fake_redis.xrange("info.changes")
    _msg_id, fields = messages[0]
    assert fields[b"key"] == b"item-1:src-9"
    assert fields[b"event_type"] == b"info_item_primary_changed"


@pytest.mark.asyncio
async def test_drain_order_preservation(session_factory, publisher, fake_redis):
    """Three rows drains in created_at order (verified via XRANGE)."""
    for sid in ("rev-a", "rev-b", "rev-c"):
        await _insert_row(session_factory, payload=_captured_event(sid))

    n = await drain_once(session_factory=session_factory, publisher=publisher)
    assert n == 3

    messages = await fake_redis.xrange("info.changes")
    assert len(messages) == 3
    keys_in_stream = [
        json.loads(fields[b"payload"])["source_revision_id"] for _, fields in messages
    ]
    assert keys_in_stream == ["rev-a", "rev-b", "rev-c"]


@pytest.mark.asyncio
async def test_drain_batch_limit(session_factory, publisher, fake_redis):
    """batch_size=2 → 2 published, 3 still pending."""
    for i in range(5):
        await _insert_row(session_factory, payload=_captured_event(f"rev-{i}"))

    n = await drain_once(session_factory=session_factory, publisher=publisher, batch_size=2)
    assert n == 2

    messages = await fake_redis.xrange("info.changes")
    assert len(messages) == 2

    async with session_factory() as s:
        result = await s.execute(
            select(ChangesOutboxRow).where(ChangesOutboxRow.published_at.is_(None))
        )
        pending = list(result.scalars())
    assert len(pending) == 3


@pytest.mark.asyncio
async def test_already_published_rows_skipped(session_factory, publisher, fake_redis):
    """Already-published row is not XADDd again; only unpublished one is."""
    already_published = await _insert_row(
        session_factory,
        payload=_captured_event("rev-old"),
        published_at=datetime.now(UTC),
    )
    pending = await _insert_row(session_factory, payload=_captured_event("rev-new"))

    n = await drain_once(session_factory=session_factory, publisher=publisher)
    assert n == 1

    messages = await fake_redis.xrange("info.changes")
    assert len(messages) == 1
    _, fields = messages[0]
    assert json.loads(fields[b"payload"])["source_revision_id"] == "rev-new"

    async with session_factory() as s:
        old = await s.get(ChangesOutboxRow, already_published.id)
        new = await s.get(ChangesOutboxRow, pending.id)
    assert old.publish_attempts == 0
    assert new.publish_attempts == 0  # success path doesn't increment failure counter


@pytest.mark.asyncio
async def test_redis_exception_row_stays_unpublished(session_factory):
    """Redis XADD failure → row unpublished, attempts incremented, last_error set."""
    row = await _insert_row(session_factory, payload=_captured_event("rev-x"))

    broken_redis = AsyncMock()
    broken_redis.xadd = AsyncMock(side_effect=ConnectionError("Redis unavailable"))
    broken_publisher = AsyncBusPublisher(broken_redis)

    n = await drain_once(session_factory=session_factory, publisher=broken_publisher)
    assert n == 1

    async with session_factory() as s:
        refreshed = await s.get(ChangesOutboxRow, row.id)

    assert refreshed.published_at is None
    assert refreshed.publish_attempts == 1
    assert refreshed.last_error is not None
    assert "Redis unavailable" in refreshed.last_error


@pytest.mark.asyncio
async def test_unknown_event_type_row_stays_unpublished(session_factory, publisher, fake_redis):
    """A row with an unrecognized event_type fails that row, not the batch."""
    bad = await _insert_row(session_factory, payload={"event_type": "who_knows"})
    good = await _insert_row(session_factory, payload=_captured_event("rev-ok"))

    n = await drain_once(session_factory=session_factory, publisher=publisher)
    assert n == 2

    # Only the good row reached the stream.
    messages = await fake_redis.xrange("info.changes")
    assert len(messages) == 1
    _, fields = messages[0]
    assert json.loads(fields[b"payload"])["source_revision_id"] == "rev-ok"

    async with session_factory() as s:
        bad_row = await s.get(ChangesOutboxRow, bad.id)
        good_row = await s.get(ChangesOutboxRow, good.id)
    assert bad_row.published_at is None
    assert bad_row.publish_attempts == 1
    assert "who_knows" in bad_row.last_error
    assert good_row.published_at is not None
