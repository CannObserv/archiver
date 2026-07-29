"""Tests for src/core/changes/publisher — outbox drain → co-core bus driver.

The drain loop reconstructs each stored outbox payload into its typed co-core
model and publishes it through ``AsyncBusPublisher`` (a ``BusPublish`` XADD),
building the wire envelope with ``co_core.pure.adapters.bus.envelope.to_wire``.
These tests assert on the canonical envelope field set (``key`` / ``payload`` /
``event_type`` / ``schema_version`` / ``occurred_at`` / ``content_type``).
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from co_core_aio.bus import AsyncBusPublisher
from fakeredis import aioredis as fakeredis_aio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.core.changes import publisher as publisher_mod
from src.core.changes.publisher import (
    DEFAULT_STREAM_MAXLEN,
    ERROR_BACKOFF_MAX_SECONDS,
    MAX_PUBLISH_ATTEMPTS,
    _error_backoff_seconds,
    _next_delay,
    drain_once,
    resolve_stream_maxlen,
    trim_stream,
)
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


# ---------------------------------------------------------------------------
# Operator-side stream retention (XTRIM) — archiver#109
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_drain_once_returns_published_not_attempted(session_factory, publisher, fake_redis):
    """drain_once returns rows *published*, not attempted — so the loop can pace
    on forward progress and not busy-wait on an all-failing batch (CR #10).

    One valid row + one poison row (unknown event_type). Only the valid one
    publishes, so the return is 1 (not 2), and the poison row is marked attempted.
    """
    await _insert_row(session_factory, payload=_captured_event("rev-ok"))
    poison = await _insert_row(
        session_factory, payload={"event_type": "totally_unknown", "schema_version": 1}
    )

    published = await drain_once(session_factory=session_factory, publisher=publisher)
    assert published == 1  # only the valid row; NOT 2 (attempted)

    messages = await fake_redis.xrange("info.changes")
    assert len(messages) == 1

    async with session_factory() as s:
        refreshed = await s.get(ChangesOutboxRow, poison.id)
    assert refreshed.published_at is None
    assert refreshed.publish_attempts == 1
    assert refreshed.last_error is not None


@pytest.mark.asyncio
async def test_drain_once_all_poison_returns_zero(session_factory, publisher):
    """An all-failing batch returns 0 → the loop will pick idle, not active."""
    await _insert_row(session_factory, payload={"event_type": "unknown_a"})
    await _insert_row(session_factory, payload={"event_type": "unknown_b"})
    published = await drain_once(session_factory=session_factory, publisher=publisher)
    assert published == 0


@pytest.mark.parametrize(
    ("consecutive", "base", "expected"),
    [
        (0, 1.0, 1.0),  # no failures → base
        (1, 1.0, 1.0),  # 1st failure → base
        (2, 1.0, 2.0),  # exponential
        (3, 1.0, 4.0),
        (4, 1.0, 8.0),
        (6, 1.0, min(32.0, ERROR_BACKOFF_MAX_SECONDS)),  # exponent clamped at shift=5
        (100, 1.0, ERROR_BACKOFF_MAX_SECONDS),  # 1.0 * 2**5 = 32 → capped at 30
        (100, 0.25, 8.0),  # 0.25 * 2**5 = 8 → below cap, so NOT capped
    ],
)
def test_error_backoff_seconds(consecutive, base, expected):
    """Consecutive whole-batch failures back off exponentially, capped (CR #13)."""
    assert _error_backoff_seconds(consecutive, base) == expected


def test_next_delay_paces_on_progress():
    """No failures: active when progress was made, idle when not (CR #10/#16)."""
    common = dict(active_interval=0.25, idle_interval=1.0, backoff_base=1.0)
    # Progress this cycle → active interval.
    assert _next_delay(consecutive_failures=0, published=5, **common) == 0.25
    # Empty batch or all rows failed (published == 0) → idle interval.
    assert _next_delay(consecutive_failures=0, published=0, **common) == 1.0


def test_next_delay_backoff_overrides_progress():
    """A whole-batch failure streak overrides the active/idle choice (CR #13/#16)."""
    common = dict(active_interval=0.25, idle_interval=1.0, backoff_base=1.0)
    # Even with published>0 from a prior cycle, an active failure streak backs off.
    assert _next_delay(consecutive_failures=1, published=5, **common) == 1.0
    assert _next_delay(consecutive_failures=3, published=0, **common) == 4.0  # 1*2**2


@pytest.mark.asyncio
async def test_run_survives_and_resets_on_persistent_then_recovered_failure(
    session_factory, publisher, monkeypatch
):
    """The loop survives repeated drain_once exceptions, logs them capped, resets
    its failure counter once a drain succeeds, and emits a recovery log (CR #13/#14)."""
    error_calls: list[int] = []
    recovery_calls: list[int] = []
    monkeypatch.setattr(
        publisher_mod.logger,
        "exception",
        lambda *a, **k: error_calls.append(k.get("extra", {}).get("consecutive_failures")),
    )
    # Recovery logs at WARNING (CR #17); capture only entries carrying after_failures.
    monkeypatch.setattr(
        publisher_mod.logger,
        "warning",
        lambda *a, **k: recovery_calls.append(k.get("extra", {}).get("after_failures")),
    )

    stop = asyncio.Event()
    calls = {"n": 0}

    async def _drain(**_kwargs):
        calls["n"] += 1
        if calls["n"] <= 3:
            raise RuntimeError("db down")
        stop.set()  # 4th call succeeds, then stop
        return 1

    monkeypatch.setattr(publisher_mod, "drain_once", _drain)

    # Tiny backoff base so the escalating error sleeps are negligible in the test.
    await publisher_mod.run(
        session_factory=session_factory,
        publisher=publisher,
        idle_interval=0.001,
        active_interval=0.001,
        error_backoff_base=0.001,
        stop_event=stop,
    )

    assert calls["n"] == 4
    # Capped logging: only the FIRST of the 3 consecutive failures is logged
    # (ERROR_LOG_EVERY caps the cadence), not one per failure.
    assert error_calls == [1]
    # Recovery: the 4th (successful) drain emits one recovery log carrying the
    # streak length it recovered from.
    assert recovery_calls == [3]


@pytest.mark.asyncio
async def test_run_no_recovery_log_without_failures(session_factory, publisher, monkeypatch):
    """A clean run (no failure streak) must NOT emit a recovery log (CR #18)."""
    recovery_calls: list[int] = []
    monkeypatch.setattr(
        publisher_mod.logger,
        "warning",
        lambda *a, **k: recovery_calls.append(k.get("extra", {}).get("after_failures")),
    )

    stop = asyncio.Event()

    async def _drain(**_kwargs):
        stop.set()
        return 0  # a clean drain, no exception, no prior failures

    monkeypatch.setattr(publisher_mod, "drain_once", _drain)

    await publisher_mod.run(
        session_factory=session_factory,
        publisher=publisher,
        idle_interval=0.001,
        active_interval=0.001,
        stop_event=stop,
    )

    assert recovery_calls == []


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, DEFAULT_STREAM_MAXLEN),  # unset → default (trim on)
        ("250000", 250000),  # explicit positive
        ("0", None),  # <= 0 disables
        ("-5", None),
        ("oops", DEFAULT_STREAM_MAXLEN),  # malformed → default, never raises
        ("", DEFAULT_STREAM_MAXLEN),  # empty → default, never raises
    ],
)
def test_resolve_stream_maxlen(raw, expected):
    """A malformed knob must degrade to the default, never raise — a bad value
    must not reach main.lifespan's broad guard and disable the whole publisher."""
    assert resolve_stream_maxlen(raw) == expected


@pytest.mark.asyncio
async def test_drain_once_accumulates_seen_topics(session_factory, publisher):
    """Each successfully-published row's topic is recorded in seen_topics."""
    await _insert_row(session_factory, topic="info.changes", payload=_captured_event("rev-x"))
    await _insert_row(session_factory, topic="other.stream", payload=_captured_event("rev-y"))

    seen: set[str] = set()
    n = await drain_once(session_factory=session_factory, publisher=publisher, seen_topics=seen)
    assert n == 2
    assert seen == {"info.changes", "other.stream"}


@pytest.mark.asyncio
async def test_run_trims_every_seen_topic(session_factory, publisher, fake_redis, monkeypatch):
    """When multiple topics were produced to, the loop trims each of them."""
    trim_calls: set[tuple[str, int]] = set()

    async def _fake_trim(client, topic, maxlen):
        trim_calls.add((topic, maxlen))

    stop = asyncio.Event()

    async def _fake_drain(*, seen_topics=None, **_kwargs):
        if seen_topics is not None:
            seen_topics.update({"info.changes", "other.stream"})
        stop.set()
        return 2

    monkeypatch.setattr(publisher_mod, "trim_stream", _fake_trim)
    monkeypatch.setattr(publisher_mod, "drain_once", _fake_drain)

    await publisher_mod.run(
        session_factory=session_factory,
        publisher=publisher,
        redis_client=fake_redis,
        stream_maxlen=100,
        trim_interval_iterations=1,
        stop_event=stop,
    )

    assert trim_calls == {("info.changes", 100), ("other.stream", 100)}


@pytest.mark.asyncio
async def test_trim_stream_issues_approximate_xtrim():
    """trim_stream caps the topic via an approximate XTRIM MAXLEN ~ N."""
    client = AsyncMock()
    await trim_stream(client, "info.changes", 100)
    client.xtrim.assert_awaited_once_with("info.changes", maxlen=100, approximate=True)


@pytest.mark.asyncio
async def test_trim_stream_bounds_a_real_stream(fake_redis):
    """Against a live (fake) stream, trim bounds XLEN at or below the cap."""
    for i in range(250):
        await fake_redis.xadd("info.changes", {"n": str(i)})
    await trim_stream(fake_redis, "info.changes", 100)
    assert await fake_redis.xlen("info.changes") <= 100


@pytest.mark.asyncio
async def test_trim_stream_swallows_errors():
    """A failing XTRIM must not propagate (the drain loop keeps running)."""
    client = AsyncMock()
    client.xtrim.side_effect = RuntimeError("redis down")
    # Should not raise.
    await trim_stream(client, "info.changes", 100)


@pytest.mark.asyncio
async def test_run_trims_periodically(session_factory, publisher, fake_redis, monkeypatch):
    """The drain loop periodically caps the stream when a client + maxlen are set."""
    trim_calls: list[tuple[str, int]] = []

    async def _fake_trim(client, topic, maxlen):
        trim_calls.append((topic, maxlen))

    stop = asyncio.Event()

    async def _fake_drain(**_kwargs):
        stop.set()  # stop after a single iteration
        return 0  # idle cycle

    monkeypatch.setattr(publisher_mod, "trim_stream", _fake_trim)
    monkeypatch.setattr(publisher_mod, "drain_once", _fake_drain)

    await publisher_mod.run(
        session_factory=session_factory,
        publisher=publisher,
        redis_client=fake_redis,
        stream_maxlen=100,
        trim_interval_iterations=1,
        stop_event=stop,
    )

    assert trim_calls == [(publisher_mod.CHANGE_STREAM_TOPIC, 100)]


@pytest.mark.asyncio
async def test_run_without_client_does_not_trim(session_factory, publisher, monkeypatch):
    """No redis_client / maxlen → no trim attempts (dormant or unconfigured)."""
    trim_calls: list[tuple[str, int]] = []

    async def _fake_trim(client, topic, maxlen):
        trim_calls.append((topic, maxlen))

    stop = asyncio.Event()

    async def _fake_drain(**_kwargs):
        stop.set()
        return 0

    monkeypatch.setattr(publisher_mod, "trim_stream", _fake_trim)
    monkeypatch.setattr(publisher_mod, "drain_once", _fake_drain)

    await publisher_mod.run(
        session_factory=session_factory,
        publisher=publisher,
        stop_event=stop,
    )

    assert trim_calls == []


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
    assert n == 0  # published count: the row failed, so nothing was published

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
    assert n == 1  # published count: only the good row (the bad one failed)

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


# ---------------------------------------------------------------------------
# Dead-lettering poison rows — archiver#107
# ---------------------------------------------------------------------------


def _legacy_captured_event(source_revision_id: str = "rev-legacy") -> dict:
    """A pre-``bindings`` source_revision_captured payload (early Phase 4, 2026-05).

    Reproduces the real prod poison rows surfaced on the archiver#109 activation:
    the ``event_type`` is known, but the payload predates ``bindings`` (carries
    ``info_item_ids`` + ``info_source_id``) and has no ``schema_version`` → today's
    co-core ``SourceRevisionCapturedEvent`` fails to validate (requires ``bindings``).
    """
    return {
        "event_type": "source_revision_captured",
        "occurred_at": "2026-05-10T12:00:00+00:00",
        "info_source_id": "01HZZ000000000000000000001",
        "source_revision_id": source_revision_id,
        "content_fingerprint": "sha256:" + "a" * 64,
        "info_item_ids": ["01HZZ000000000000000000003"],
    }


@pytest.mark.asyncio
async def test_unknown_event_type_dead_lettered_and_not_reselected(
    session_factory, publisher, fake_redis
):
    """An unknown event_type is a permanent failure → dead-lettered on the first
    drain, then never selected again (no infinite retry / log-spam) — archiver#107."""
    bad = await _insert_row(session_factory, payload={"event_type": "who_knows"})

    n1 = await drain_once(session_factory=session_factory, publisher=publisher)
    assert n1 == 0

    async with session_factory() as s:
        row = await s.get(ChangesOutboxRow, bad.id)
    assert row.dead_lettered_at is not None
    assert row.published_at is None
    assert row.publish_attempts == 1
    assert "who_knows" in row.last_error

    # Second drain must NOT re-attempt it — the row is no longer selected.
    n2 = await drain_once(session_factory=session_factory, publisher=publisher)
    assert n2 == 0
    async with session_factory() as s:
        row2 = await s.get(ChangesOutboxRow, bad.id)
    assert row2.publish_attempts == 1  # unchanged — not re-selected


@pytest.mark.asyncio
async def test_corrupt_legacy_payload_dead_lettered(session_factory, publisher, fake_redis):
    """A known event_type with an unvalidatable (pre-bindings) payload is
    dead-lettered immediately — reproduces the archiver#109 prod poison rows."""
    poison = await _insert_row(session_factory, payload=_legacy_captured_event("rev-legacy-1"))

    n = await drain_once(session_factory=session_factory, publisher=publisher)
    assert n == 0

    # Nothing reached the stream.
    assert await fake_redis.xrange("info.changes") == []

    async with session_factory() as s:
        row = await s.get(ChangesOutboxRow, poison.id)
    assert row.dead_lettered_at is not None
    assert row.published_at is None
    assert row.publish_attempts == 1
    assert row.last_error is not None


@pytest.mark.asyncio
async def test_transient_failure_not_dead_lettered(session_factory):
    """A transient publish failure (Redis down) must NOT dead-letter — the row
    stays live and is retried next drain (only deterministic poison is retired)."""
    row = await _insert_row(session_factory, payload=_captured_event("rev-x"))

    broken = AsyncMock()
    broken.xadd = AsyncMock(side_effect=ConnectionError("Redis unavailable"))
    broken_publisher = AsyncBusPublisher(broken)

    n = await drain_once(session_factory=session_factory, publisher=broken_publisher)
    assert n == 0

    async with session_factory() as s:
        refreshed = await s.get(ChangesOutboxRow, row.id)
    assert refreshed.dead_lettered_at is None  # transient → still live
    assert refreshed.published_at is None
    assert refreshed.publish_attempts == 1


@pytest.mark.asyncio
async def test_attempt_ceiling_dead_letters_persistent_failure(session_factory):
    """Backstop: a row that keeps failing transiently past MAX_PUBLISH_ATTEMPTS is
    dead-lettered, so an unclassified *persistent* failure can't spin forever."""
    row = await _insert_row(session_factory, payload=_captured_event("rev-stuck"))
    # Pre-age it to one attempt below the ceiling so a single failing drain crosses it.
    async with session_factory() as s:
        r = await s.get(ChangesOutboxRow, row.id)
        r.publish_attempts = MAX_PUBLISH_ATTEMPTS - 1
        await s.commit()

    broken = AsyncMock()
    broken.xadd = AsyncMock(side_effect=ConnectionError("still down"))
    broken_publisher = AsyncBusPublisher(broken)

    n = await drain_once(session_factory=session_factory, publisher=broken_publisher)
    assert n == 0

    async with session_factory() as s:
        refreshed = await s.get(ChangesOutboxRow, row.id)
    assert refreshed.publish_attempts == MAX_PUBLISH_ATTEMPTS
    assert refreshed.dead_lettered_at is not None
