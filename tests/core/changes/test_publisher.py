"""Tests for src/core/changes/publisher — outbox drain → Redis Stream."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
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


async def _insert_row(
    session_factory: async_sessionmaker,
    topic: str = "info.changes",
    payload: dict | None = None,
    published_at: datetime | None = None,
) -> ChangesOutboxRow:
    """Insert one ChangesOutboxRow and return it (refreshed)."""
    row = ChangesOutboxRow(
        topic=topic,
        payload=payload or {"source_revision_id": "rev-1"},
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
async def test_drain_empty(session_factory, fake_redis):
    """Empty outbox → drain returns 0, no XADD calls."""
    n = await drain_once(session_factory=session_factory, redis=fake_redis)
    assert n == 0
    # No stream keys created
    keys = await fake_redis.keys("*")
    assert keys == []


@pytest.mark.asyncio
async def test_drain_single_row(session_factory, fake_redis):
    """Single row drains: XADD called once; row updated correctly."""
    row = await _insert_row(
        session_factory, topic="info.changes", payload={"source_revision_id": "rev-42"}
    )

    n = await drain_once(session_factory=session_factory, redis=fake_redis)

    assert n == 1

    # Verify stream has exactly one message
    messages = await fake_redis.xrange("info.changes")
    assert len(messages) == 1
    _msg_id, fields = messages[0]

    assert fields[b"key"] == b"rev-42"
    parsed = json.loads(fields[b"payload"])
    assert parsed["source_revision_id"] == "rev-42"

    # Verify DB row updated
    async with session_factory() as s:
        refreshed = await s.get(ChangesOutboxRow, row.id)
    assert refreshed is not None
    assert refreshed.published_at is not None
    assert refreshed.bus_message_id is not None
    assert refreshed.publish_attempts == 0  # success path doesn't increment failure counter
    assert refreshed.last_error is None


@pytest.mark.asyncio
async def test_drain_order_preservation(session_factory, fake_redis):
    """Three rows drains in created_at order (verified via XRANGE)."""
    # Insert with explicit created_at so ordering is deterministic
    payloads = [
        {"source_revision_id": "rev-a"},
        {"source_revision_id": "rev-b"},
        {"source_revision_id": "rev-c"},
    ]
    for p in payloads:
        await _insert_row(session_factory, payload=p)

    n = await drain_once(session_factory=session_factory, redis=fake_redis)
    assert n == 3

    messages = await fake_redis.xrange("info.changes")
    assert len(messages) == 3

    keys_in_stream = [
        json.loads(fields[b"payload"])["source_revision_id"] for _, fields in messages
    ]
    assert keys_in_stream == ["rev-a", "rev-b", "rev-c"]


@pytest.mark.asyncio
async def test_drain_batch_limit(session_factory, fake_redis):
    """batch_size=2 → 2 published, 3 still pending."""
    for i in range(5):
        await _insert_row(session_factory, payload={"source_revision_id": f"rev-{i}"})

    n = await drain_once(session_factory=session_factory, redis=fake_redis, batch_size=2)
    assert n == 2

    # Verify only 2 messages in stream
    messages = await fake_redis.xrange("info.changes")
    assert len(messages) == 2

    # Verify 3 unpublished rows remain
    async with session_factory() as s:
        result = await s.execute(
            select(ChangesOutboxRow).where(ChangesOutboxRow.published_at.is_(None))
        )
        pending = list(result.scalars())
    assert len(pending) == 3


@pytest.mark.asyncio
async def test_already_published_rows_skipped(session_factory, fake_redis):
    """Already-published row is not XADDd again; only unpublished one is."""
    already_published = await _insert_row(
        session_factory,
        payload={"source_revision_id": "rev-old"},
        published_at=datetime.now(UTC),
    )
    pending = await _insert_row(session_factory, payload={"source_revision_id": "rev-new"})

    n = await drain_once(session_factory=session_factory, redis=fake_redis)
    assert n == 1

    messages = await fake_redis.xrange("info.changes")
    assert len(messages) == 1
    _, fields = messages[0]
    assert json.loads(fields[b"payload"])["source_revision_id"] == "rev-new"

    # The already-published row is untouched
    async with session_factory() as s:
        old = await s.get(ChangesOutboxRow, already_published.id)
        new = await s.get(ChangesOutboxRow, pending.id)
    assert old.publish_attempts == 0
    assert new.publish_attempts == 0  # success path doesn't increment failure counter


@pytest.mark.asyncio
async def test_redis_exception_row_stays_unpublished(session_factory):
    """Redis XADD failure → row unpublished, attempts incremented, last_error set."""
    row = await _insert_row(session_factory, payload={"source_revision_id": "rev-x"})

    broken_redis = AsyncMock()
    broken_redis.xadd = AsyncMock(side_effect=ConnectionError("Redis unavailable"))

    n = await drain_once(session_factory=session_factory, redis=broken_redis)
    assert n == 1

    async with session_factory() as s:
        refreshed = await s.get(ChangesOutboxRow, row.id)

    assert refreshed.published_at is None
    assert refreshed.publish_attempts == 1
    assert refreshed.last_error is not None
    assert "Redis unavailable" in refreshed.last_error
