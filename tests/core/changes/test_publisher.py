"""Tests for src/core/changes/publisher - outbox drain → co-core bus driver.

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
from co_core.pure.adapters.bus.envelope import _PAYLOAD_BY_EVENT_TYPE
from co_core.pure.adapters.bus.exceptions import (
    BusMessageMalformedPayloadError,
    BusMessageUnknownEventTypeError,
)
from co_core_aio.bus import AsyncBusPublisher
from fakeredis import aioredis as fakeredis_aio
from redis.exceptions import OutOfMemoryError, ResponseError
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.core.changes import publisher as publisher_mod
from src.core.changes.publisher import (
    DEFAULT_STREAM_MAXLEN,
    MAX_PUBLISH_ATTEMPTS,
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
    ``drain_once`` can open and commit its own session - matching production
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

# The single ``occurred_at`` every payload fixture in this module stamps. One
# constant because two consumers derive from it and would otherwise drift from the
# payloads they describe (CR round 1, finding 5; round 2, finding 8): the
# idempotency keys that embed a timestamp (``fetch_failed``, ``fetch_policy``) and
# the hoisted-envelope assertions.
_OCCURRED_AT = "2026-07-28T12:00:00+00:00"

# The ``info_source_id`` every content-contract fixture carries. Required across
# all three of them since cannobserv#300, and it is half of the
# ``source_revision_observed`` idempotency key - so, like _OCCURRED_AT, one
# constant rather than a literal per fixture free to drift from the key it feeds.
_INFO_SOURCE_ID = "01JQ0000000000000000000001"


def _captured_event(source_revision_id: str = "rev-1") -> dict:
    """A full ``source_revision_captured`` payload as stored in the outbox.

    Matches ``model_dump(mode="json")`` of the co-core event the route emits.
    """
    return {
        "schema_version": 2,
        "event_type": "source_revision_captured",
        "occurred_at": _OCCURRED_AT,
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
        "occurred_at": _OCCURRED_AT,
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
    assert fields[b"occurred_at"] == _OCCURRED_AT.encode()
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
    yielding an empty key for this type - co-core's ``idempotency_key`` fixes it.)
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
# Operator-side stream retention (XTRIM) - archiver#109
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_drain_once_returns_published_not_attempted(session_factory, publisher, fake_redis):
    """drain_once returns rows *published*, not attempted - so the loop can pace
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


# The backoff schedule itself moved to src/core/changes/backoff.py and is tested
# in test_backoff.py; _next_delay's own pacing choice is still the publisher's.


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
    """A malformed knob must degrade to the default, never raise - a bad value
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
# Dead-lettering poison rows - archiver#107
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
    drain, then never selected again (no infinite retry / log-spam) - archiver#107."""
    bad = await _insert_row(session_factory, payload={"event_type": "who_knows"})

    n1 = await drain_once(session_factory=session_factory, publisher=publisher)
    assert n1 == 0

    async with session_factory() as s:
        row = await s.get(ChangesOutboxRow, bad.id)
    assert row.dead_lettered_at is not None
    assert row.published_at is None
    assert row.publish_attempts == 1
    assert "who_knows" in row.last_error

    # Second drain must NOT re-attempt it - the row is no longer selected.
    n2 = await drain_once(session_factory=session_factory, publisher=publisher)
    assert n2 == 0
    async with session_factory() as s:
        row2 = await s.get(ChangesOutboxRow, bad.id)
    assert row2.publish_attempts == 1  # unchanged - not re-selected


@pytest.mark.asyncio
async def test_corrupt_legacy_payload_dead_lettered(session_factory, publisher, fake_redis):
    """A known event_type with an unvalidatable (pre-bindings) payload is
    dead-lettered immediately - reproduces the archiver#109 prod poison rows."""
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
async def test_build_phase_last_error_names_co_core_anomaly(session_factory, publisher, fake_redis):
    """archiver#108: build-phase reconstruction now goes through co-core's shared
    ``payload_from_dict``, so a poison row's ``last_error`` records a
    ``BusMessageAnomaly`` subclass - not the old bare ``ValueError``. Locks in the
    error-type contract (CR round 1, finding 8) so downstream ``last_error``
    grepping expects the co-core type."""
    unknown = await _insert_row(session_factory, payload={"event_type": "who_knows"})
    malformed = await _insert_row(session_factory, payload=_legacy_captured_event("rev-legacy-2"))

    n = await drain_once(session_factory=session_factory, publisher=publisher)
    assert n == 0

    async with session_factory() as s:
        unknown_row = await s.get(ChangesOutboxRow, unknown.id)
        malformed_row = await s.get(ChangesOutboxRow, malformed.id)
    assert BusMessageUnknownEventTypeError.__name__ in unknown_row.last_error
    assert BusMessageMalformedPayloadError.__name__ in malformed_row.last_error


@pytest.mark.asyncio
async def test_build_phase_last_error_carries_the_underlying_cause(
    session_factory, publisher, fake_redis
):
    """``last_error`` must carry co-core's *remedy* text, not just the wrapper.

    ``payload_from_dict`` raises a ``BusMessageAnomaly`` whose own message names
    only the event_type - the sentence saying which field is wrong and how to fix
    it lives on the chained ``__cause__`` (a pydantic ``ValidationError``). A bare
    ``repr(exc)`` is 123 characters of "has a malformed payload" and discards it.

    That matters because ``last_error`` on a dead-lettered row is the *entire*
    diagnostic an operator gets: the build phase is pure, so there is no retry to
    observe and no stream entry to inspect. cannobserv#324 wrote a remedy string
    for exactly this read path ("to delegate to the consumer default, send
    {"schema_version": 1} with no "interval""); dropping the cause makes the
    loud-failure guarantee that tightening bought degrade to "something is wrong".
    """
    live_missing_watch_spec = {
        "schema_version": 1,
        "event_type": "registry_announcement",
        "occurred_at": _OCCURRED_AT,
        "info_item_id": "item-nospec",
        "generation": 1,
        "info_source_id": _INFO_SOURCE_ID,
        "url": "https://example.test/doc",
        "source_specs": [{"selector": "main"}],
    }
    poison = await _insert_row(session_factory, payload=live_missing_watch_spec)

    assert await drain_once(session_factory=session_factory, publisher=publisher) == 0

    async with session_factory() as s:
        row = await s.get(ChangesOutboxRow, poison.id)
    assert row.dead_lettered_at is not None
    # The wrapper type is still named (test above pins that contract) ...
    assert BusMessageMalformedPayloadError.__name__ in row.last_error
    # ... and the cause's remedy text survives to the row an operator reads.
    assert "watch_spec" in row.last_error


@pytest.mark.asyncio
async def test_transient_failure_not_dead_lettered(session_factory):
    """A transient publish failure (Redis down) must NOT dead-letter - the row
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
async def test_attempt_ceiling_dead_letters_non_transient_failure(session_factory):
    """Backstop: a NON-transient publish failure (e.g. a server-side ResponseError)
    that persists past MAX_PUBLISH_ATTEMPTS is dead-lettered so it can't spin
    forever. Only non-transient errors count toward the ceiling (CR #2)."""
    row = await _insert_row(session_factory, payload=_captured_event("rev-stuck"))
    # Pre-age it to one attempt below the ceiling so a single failing drain crosses it.
    async with session_factory() as s:
        r = await s.get(ChangesOutboxRow, row.id)
        r.publish_attempts = MAX_PUBLISH_ATTEMPTS - 1
        await s.commit()

    broken = AsyncMock()
    broken.xadd = AsyncMock(side_effect=ResponseError("WRONGTYPE"))
    broken_publisher = AsyncBusPublisher(broken)

    n = await drain_once(session_factory=session_factory, publisher=broken_publisher)
    assert n == 0

    async with session_factory() as s:
        refreshed = await s.get(ChangesOutboxRow, row.id)
    assert refreshed.publish_attempts == MAX_PUBLISH_ATTEMPTS
    assert refreshed.dead_lettered_at is not None


@pytest.mark.asyncio
async def test_transient_failure_exempt_from_ceiling(session_factory):
    """A *transient* failure (Redis down) is NEVER dead-lettered by the ceiling -
    even past MAX_PUBLISH_ATTEMPTS it keeps retrying, so a long-but-genuine outage
    cannot silently drop a valid event (CR #2, the data-loss-cliff guard)."""
    row = await _insert_row(session_factory, payload=_captured_event("rev-outage"))
    # Pre-age it ABOVE the ceiling - a non-transient error here would dead-letter.
    async with session_factory() as s:
        r = await s.get(ChangesOutboxRow, row.id)
        r.publish_attempts = MAX_PUBLISH_ATTEMPTS
        await s.commit()

    broken = AsyncMock()
    broken.xadd = AsyncMock(side_effect=ConnectionError("still down"))
    broken_publisher = AsyncBusPublisher(broken)

    n = await drain_once(session_factory=session_factory, publisher=broken_publisher)
    assert n == 0

    async with session_factory() as s:
        refreshed = await s.get(ChangesOutboxRow, row.id)
    assert refreshed.dead_lettered_at is None  # transient → exempt, still live
    assert refreshed.publish_attempts == MAX_PUBLISH_ATTEMPTS + 1  # keeps climbing


@pytest.mark.asyncio
async def test_broker_oom_is_transient_and_exempt_from_ceiling(session_factory):
    """A broker OOM (``maxmemory`` reached under ``noeviction``) is TRANSIENT.

    archiver#128: the drop-in now sets an explicit ``maxmemory``, so memory
    pressure surfaces as ``OOM command not allowed`` - a ``ResponseError``
    subclass - instead of the kernel OOM-killing the broker. That is an outage
    the operator resolves, not poison in the row: the event is valid and must
    survive until the broker has room. Classifying it with ``WRONGTYPE`` would
    dead-letter valid ``info.changes`` events during a memory incident caused by
    an unrelated stream on the shared broker.
    """
    row = await _insert_row(session_factory, payload=_captured_event("rev-oom"))
    # Pre-age it ABOVE the ceiling: a non-transient error here would dead-letter.
    async with session_factory() as s:
        r = await s.get(ChangesOutboxRow, row.id)
        r.publish_attempts = MAX_PUBLISH_ATTEMPTS
        await s.commit()

    broken = AsyncMock()
    broken.xadd = AsyncMock(
        side_effect=OutOfMemoryError("OOM command not allowed when used memory > 'maxmemory'.")
    )
    broken_publisher = AsyncBusPublisher(broken)

    n = await drain_once(session_factory=session_factory, publisher=broken_publisher)
    assert n == 0

    async with session_factory() as s:
        refreshed = await s.get(ChangesOutboxRow, row.id)
    assert refreshed.dead_lettered_at is None  # transient → exempt, still live
    assert refreshed.published_at is None
    assert refreshed.publish_attempts == MAX_PUBLISH_ATTEMPTS + 1  # keeps climbing


@pytest.mark.asyncio
async def test_dead_letter_logs_error_with_reason(session_factory, publisher, monkeypatch):
    """Dead-lettering emits an ERROR log carrying the reason - the only operator
    signal a poison row was retired until the Phase 3 dashboard surfaces it (CR #4)."""
    error_reasons: list[str | None] = []
    monkeypatch.setattr(
        publisher_mod.logger,
        "error",
        lambda *a, **k: error_reasons.append(k.get("extra", {}).get("reason")),
    )

    # Build-phase poison → reason "unpublishable_payload".
    await _insert_row(session_factory, payload={"event_type": "who_knows"})
    await drain_once(session_factory=session_factory, publisher=publisher)
    assert error_reasons == ["unpublishable_payload"]

    # Non-transient publish failure past the ceiling → reason "attempts_exhausted".
    row = await _insert_row(session_factory, payload=_captured_event("rev-ceil"))
    async with session_factory() as s:
        r = await s.get(ChangesOutboxRow, row.id)
        r.publish_attempts = MAX_PUBLISH_ATTEMPTS - 1
        await s.commit()
    broken = AsyncMock()
    broken.xadd = AsyncMock(side_effect=ResponseError("WRONGTYPE"))
    await drain_once(session_factory=session_factory, publisher=AsyncBusPublisher(broken))
    assert error_reasons == ["unpublishable_payload", "attempts_exhausted"]


# ---------------------------------------------------------------------------
# The widened ChangeEventPayload union - archiver#138, widened again by #139
# ---------------------------------------------------------------------------
#
# The co-core 0.7 line grew the union from four members to six: ContentFetchCommand
# gained ``command_id`` (cannobserv#266), BlobAvailableEvent gained the correlation
# + enrichment fields (#266/#271), and FetchFailedEvent (#270) / FetchPolicyState
# (#285) are new. co-core 0.8 makes it seven, adding SourceRevisionObservedEvent
# (cannobserv#301) - the fact Archiver *consumes* under #139, listed here because
# membership of the union is what the publisher dispatches on, not direction.
#
# 0.8 also made ``info_source_id`` required across all three content contracts
# (cannobserv#300), and re-keyed ``blob_available`` from the bare fingerprint to
# ``content_fingerprint:command_id`` so one fact per *occurrence* survives two
# InfoSources sharing a URL. The fixtures below carry both.
#
# Archiver produces only the two ``info.changes`` types, but the publisher
# dispatches through co-core's single ``_PAYLOAD_BY_EVENT_TYPE`` table - so the
# drain loop is a viable transport for any of the seven, and the
# unknown-``event_type`` dead-letter branch (archiver#107) must still fire only for
# an event type outside the *widened* union. These lock both halves in.


# Payload fields typed as tz-aware datetimes across the union - compared as
# instants rather than strings in the round-trip assertion below, because co-core
# spells them two ways in one message (cannobserv#305): the hoisted envelope field
# and the idempotency key use ``isoformat()`` (``+00:00``) while the embedded
# payload JSON uses pydantic's default (``Z``). Harmless for Archiver - nothing
# here string-matches a payload timestamp - so this stays a test-side accommodation
# rather than a workaround in ``publisher.py``. Drop it if #305 lands.
_DATETIME_PAYLOAD_FIELDS = frozenset(
    {"occurred_at", "fetched_at", "captured_at", "blob_expires_at"}
)


def _parse_instant(raw: str) -> datetime:
    """Parse an ISO-8601 instant, accepting either the ``Z`` or ``+00:00`` spelling.

    The suffix is stripped anchored, not replaced globally - a bare ``replace("Z",
    …)`` reads as "strip the suffix" but would rewrite a ``Z`` anywhere in the
    string (CR round 1, finding 4).
    """
    return datetime.fromisoformat(raw[:-1] + "+00:00" if raw.endswith("Z") else raw)


def _content_fetch_command(command_id: str = "cmd-1") -> dict:
    """A full ``content_fetch`` command payload (cannobserv#266 + #300 shape)."""
    return {
        "schema_version": 1,
        "event_type": "content_fetch",
        "occurred_at": _OCCURRED_AT,
        "command_id": command_id,
        "url": "https://example.test/a",
        "info_source_id": _INFO_SOURCE_ID,
        "headers": {"User-Agent": "co-observer"},
        "timeout_seconds": 30.0,
    }


def _blob_available_event(content_fingerprint: str = "sha256:" + "b" * 64) -> dict:
    """A full ``blob_available`` payload - #266 correlation, #271 enrichment, #300 key."""
    return {
        "schema_version": 1,
        "event_type": "blob_available",
        "occurred_at": _OCCURRED_AT,
        "content_fingerprint": content_fingerprint,
        "blob_uri": "file:///var/lib/replicator/blobs/b",
        "size_bytes": 1234,
        "media_type": "text/html",
        "url": "https://example.test/a",
        "command_id": "cmd-1",
        "info_source_id": _INFO_SOURCE_ID,
        "final_url": "https://example.test/a/",
        "status_code": 200,
        "fetched_at": "2026-07-28T11:59:00+00:00",
        "content_type_raw": "text/html; charset=utf-8",
        "etag": 'W/"abc"',
        "last_modified": "Mon, 27 Jul 2026 00:00:00 GMT",
        "blob_expires_at": "2026-08-04T11:59:00+00:00",
    }


def _fetch_failed_event(command_id: str = "cmd-2") -> dict:
    """A full ``fetch_failed`` payload (cannobserv#270 + #300)."""
    return {
        "schema_version": 1,
        "event_type": "fetch_failed",
        "occurred_at": _OCCURRED_AT,
        "command_id": command_id,
        "url": "https://example.test/b",
        "info_source_id": _INFO_SOURCE_ID,
        "reason": "http_error",
        "terminal": True,
        "status_code": 503,
        "attempts": 3,
        "detail": "upstream unavailable",
    }


def _source_revision_observed_event(
    extracted_fingerprint: str = "sha256:" + "d" * 64,
) -> dict:
    """A full ``source_revision_observed`` payload (cannobserv#301).

    The fact Archiver consumes under #139. ``extracted_fingerprint`` is sha256 of
    the text extracted under ``source_specs`` - never the blob's raw-byte
    ``content_fingerprint``, which is why the field names differ.
    """
    return {
        "schema_version": 1,
        "event_type": "source_revision_observed",
        "occurred_at": _OCCURRED_AT,
        "info_source_id": _INFO_SOURCE_ID,
        "extracted_fingerprint": extracted_fingerprint,
        "captured_at": "2026-07-28T11:59:00+00:00",
        "content_size_bytes": 4096,
        "content_media_type": "text/plain",
        "source_media_type": "text/html",
        "blob_uri": "file:///var/lib/replicator/blobs/d",
        "blob_expires_at": "2026-08-04T11:59:00+00:00",
        "command_id": "cmd-3",
        "spec_fingerprint": "sha256:" + "e" * 64,
    }


def _registry_announcement_state(info_item_id: str = "item-r") -> dict:
    """A full ``registry_announcement`` config/state payload (cannobserv#302, #324).

    ``watch_spec`` is required on a *live* announcement as of co-core v0.9.3 -
    it joined ``info_source_id`` / ``url`` / ``source_specs`` in the
    required-unless-revoked set. ``{"schema_version": 1}`` with no ``interval``
    is the delegation spelling ("consumer applies its own default"), which is
    what archiver#150's ``DEFAULT_WATCH_SPEC`` stores.
    """
    return {
        "schema_version": 1,
        "event_type": "registry_announcement",
        "occurred_at": _OCCURRED_AT,
        "info_item_id": info_item_id,
        "generation": 7,
        "info_source_id": _INFO_SOURCE_ID,
        "url": "https://example.test/doc",
        "source_specs": [{"selector": "main"}],
        "active": True,
        "watch_spec": {"schema_version": 1},
        "revoked": False,
    }


def _watch_status_state(info_item_id: str = "item-w") -> dict:
    """A full ``watch_status`` config/state payload (cannobserv#321).

    The return leg Archiver *consumes* under archiver#151; it is in the union
    (and so in this guard) because ``payload_from_dict`` dispatches on one table
    for both directions.
    """
    return {
        "schema_version": 1,
        "event_type": "watch_status",
        "occurred_at": _OCCURRED_AT,
        "info_item_id": info_item_id,
        "applied_generation": 7,
        "applied_active": True,
        "applied_interval": "1d",
        "last_attempt_at": "2026-07-28T11:59:00+00:00",
        "last_observed_at": "2026-07-28T11:59:00+00:00",
        "health": "ok",
        "revoked": False,
    }


def _fetch_policy_state(host: str = "example.test") -> dict:
    """A full ``fetch_policy`` config/state payload (cannobserv#285)."""
    return {
        "schema_version": 1,
        "event_type": "fetch_policy",
        "occurred_at": _OCCURRED_AT,
        "host": host,
        "min_interval_seconds": 2.5,
        "revoked": False,
    }


# One case per union member: (stored outbox payload, event_type, expected wire key).
def _content_replicate_command(command_id: str = "cmd-r") -> dict:
    """A full ``content_replicate`` command payload (cannobserv#303).

    What archiver#169 writes to the outbox. ``destination`` is *rendered* - the
    RepSpec's path_template never travels (the issuer contract's T3).
    """
    return {
        "schema_version": 1,
        "event_type": "content_replicate",
        "occurred_at": _OCCURRED_AT,
        "command_id": command_id,
        "blob_uri": "file:///var/lib/replicator/blobs/aa/bb/" + "e" * 64 + ".bin",
        "media_type": "text/html",
        "provider": "gcs",
        "credentials_alias": "gcs-cannobserv-prod",
        "destination": "archive/wa-lcb/" + "e" * 64 + ".html",
        "object_options": {"storage_class": "STANDARD"},
        "info_item_rep_spec_id": "01JQ0000000000000000000002",
        "source_revision_id": "01JQ0000000000000000000003",
        "info_source_id": _INFO_SOURCE_ID,
    }


def _replication_complete_event(command_id: str = "cmd-rc") -> dict:
    """A full ``replication_complete`` payload - the fact archiver#170 consumes."""
    return {
        "schema_version": 1,
        "event_type": "replication_complete",
        "occurred_at": _OCCURRED_AT,
        "command_id": command_id,
        "public_url": "https://storage.googleapis.com/co-archive/archive/wa-lcb/x.html",
        "info_item_rep_spec_id": "01JQ0000000000000000000002",
        "source_revision_id": "01JQ0000000000000000000003",
        "info_source_id": _INFO_SOURCE_ID,
    }


def _replication_failed_event(command_id: str = "cmd-rf") -> dict:
    """A full ``replication_failed`` payload. ``reason`` is producer-owned and opaque."""
    return {
        "schema_version": 1,
        "event_type": "replication_failed",
        "occurred_at": _OCCURRED_AT,
        "command_id": command_id,
        "info_item_rep_spec_id": "01JQ0000000000000000000002",
        "source_revision_id": "01JQ0000000000000000000003",
        "info_source_id": _INFO_SOURCE_ID,
        "reason": "blob_expired",
        "terminal": True,
        "attempts": 1,
        "detail": "blob is past its horizon",
    }


# The single source for both the parametrize below and the completeness guard that
# pins it to co-core's dispatch table (CR round 1, finding 3).
_UNION_CASES = [
    (_captured_event("rev-u"), "source_revision_captured", "rev-u"),
    (
        _primary_changed_event(info_item_id="item-u", new_info_source_id="src-u"),
        "info_item_primary_changed",
        "item-u:src-u",
    ),
    (_content_fetch_command("cmd-u"), "content_fetch", "cmd-u"),
    # #300 re-keyed this from the bare fingerprint to fingerprint:command_id.
    (
        _blob_available_event("sha256:" + "c" * 64),
        "blob_available",
        "sha256:" + "c" * 64 + ":cmd-1",
    ),
    (_fetch_failed_event("cmd-f"), "fetch_failed", f"cmd-f:{_OCCURRED_AT}"),
    (_fetch_policy_state("policy.test"), "fetch_policy", f"policy.test:{_OCCURRED_AT}"),
    # Slot-shaped key, mirroring uq_source_revisions_source_fingerprint - the one
    # documented exception to the union's occurrence-per-key invariant (#301).
    (
        _source_revision_observed_event("sha256:" + "d" * 64),
        "source_revision_observed",
        f"{_INFO_SOURCE_ID}:{'sha256:' + 'd' * 64}",
    ),
    # Both config/state streams key on info_item_id:occurred_at, following
    # fetch_policy - an *occurrence*; the LWW slot is the info_item_id field.
    (
        _registry_announcement_state("item-r"),
        "registry_announcement",
        f"item-r:{_OCCURRED_AT}",
    ),
    (_watch_status_state("item-w"), "watch_status", f"item-w:{_OCCURRED_AT}"),
    # The replicate trio (cannobserv#303). The command keys on command_id alone,
    # exactly as content_fetch does; both outcome facts key on
    # command_id:occurred_at, because one command legitimately emits more than
    # one - T4's no-op row re-emits a success for an artifact already written.
    (_content_replicate_command("cmd-r"), "content_replicate", "cmd-r"),
    (
        _replication_complete_event("cmd-rc"),
        "replication_complete",
        f"cmd-rc:{_OCCURRED_AT}",
    ),
    (_replication_failed_event("cmd-rf"), "replication_failed", f"cmd-rf:{_OCCURRED_AT}"),
]


def test_union_cases_cover_every_co_core_payload_type():
    """The parametrize below must cover co-core's dispatch table exactly.

    Without this, "all six members round-trip" decays silently: co-core adds a
    seventh (cannobserv#301 and #303 are open and both propose new payloads), the
    suite still passes, and the coverage claim quietly becomes six-of-seven with no
    signal. Reaching for the private ``_PAYLOAD_BY_EVENT_TYPE`` is the deliberate
    trade - it is the table ``payload_from_dict`` actually dispatches on, so
    anything else here would be a second list free to drift from it.
    """
    assert {event_type for _, event_type, _ in _UNION_CASES} == set(_PAYLOAD_BY_EVENT_TYPE)


@pytest.mark.parametrize(
    ("payload", "expected_event_type", "expected_key"),
    _UNION_CASES,
    ids=[event_type for _, event_type, _ in _UNION_CASES],
)
@pytest.mark.asyncio
async def test_drain_round_trips_every_union_member(
    session_factory, publisher, fake_redis, payload, expected_event_type, expected_key
):
    """Every member of the widened union survives outbox dict → typed model → wire.

    Guards the pin: on co-core 0.6 four of these six event types either did not
    exist or carried a different field set, so the payload would have been
    dead-lettered as unpublishable rather than published.
    """
    topic = f"test.{expected_event_type}"
    await _insert_row(session_factory, topic=topic, payload=payload)

    n = await drain_once(session_factory=session_factory, publisher=publisher)
    assert n == 1

    messages = await fake_redis.xrange(topic)
    assert len(messages) == 1
    _msg_id, fields = messages[0]
    assert fields[b"event_type"] == expected_event_type.encode()
    assert fields[b"key"] == expected_key.encode()
    assert fields[b"content_type"] == b"application/json"
    assert fields[b"occurred_at"] == _OCCURRED_AT.encode()

    # The JSON payload round-trips every field the outbox row stored. Datetime
    # fields are compared as *instants*, not strings - see the cannobserv#305 note
    # on _DATETIME_PAYLOAD_FIELDS above. Only the instant is contractual.
    parsed = json.loads(fields[b"payload"])
    for field, value in payload.items():
        if field in _DATETIME_PAYLOAD_FIELDS:
            assert _parse_instant(parsed[field]) == _parse_instant(value)
        else:
            assert parsed[field] == value


@pytest.mark.asyncio
async def test_unknown_event_type_still_dead_lettered_after_union_widened(
    session_factory, publisher
):
    """The archiver#107 dead-letter branch still fires for a type outside the
    *widened* union - the six new/changed members did not turn poison into a
    publishable row."""
    bad = await _insert_row(session_factory, payload={"event_type": "content_fetched"})

    assert await drain_once(session_factory=session_factory, publisher=publisher) == 0

    async with session_factory() as s:
        row = await s.get(ChangesOutboxRow, bad.id)
    assert row.dead_lettered_at is not None
    assert BusMessageUnknownEventTypeError.__name__ in row.last_error


@pytest.mark.asyncio
async def test_naive_occurred_at_dead_lettered(session_factory, publisher, fake_redis):
    """``OccurredAt`` (cannobserv#273) rejects a naive datetime fail-loud, so a row
    carrying one is build-phase poison - dead-lettered, never published with an
    ambiguous timestamp."""
    # The same stamp with the offset stripped - derived, so it stays the naive
    # spelling of _OCCURRED_AT rather than a second literal free to drift from it.
    naive = {
        **_content_fetch_command("cmd-naive"),
        "occurred_at": _OCCURRED_AT.removesuffix("+00:00"),
    }
    row = await _insert_row(session_factory, payload=naive)

    assert await drain_once(session_factory=session_factory, publisher=publisher) == 0
    assert await fake_redis.xrange("info.changes") == []

    async with session_factory() as s:
        refreshed = await s.get(ChangesOutboxRow, row.id)
    assert refreshed.dead_lettered_at is not None
    assert BusMessageMalformedPayloadError.__name__ in refreshed.last_error


@pytest.mark.asyncio
async def test_registry_topic_publish_carries_its_own_maxlen(session_factory, fake_redis):
    """info.registry retention rides the publish, not the XTRIM loop.

    co-core's stream taxonomy: a config/state stream's retention is a consumer
    contract carried by BusPublish.maxlen, because consumers boot by replaying
    from 0-0 - out-of-band operator trimming sized for the fact stream would
    silently violate the "at least one full snapshot plus deltas" floor.
    """
    captured: list = []
    real = AsyncBusPublisher(fake_redis)

    class SpyPublisher:
        async def execute(self, effect):
            captured.append(effect)
            return await real.execute(effect)

    await _insert_row(
        session_factory, payload=_registry_announcement_state("item-maxlen"), topic="info.registry"
    )
    await _insert_row(session_factory, payload=_captured_event("rev-nomaxlen"))

    n = await drain_once(
        session_factory=session_factory,
        publisher=SpyPublisher(),
        topic_maxlen={"info.registry": 50_000},
    )
    assert n == 2

    by_topic = {e.topic: e for e in captured}
    assert by_topic["info.registry"].maxlen == 50_000
    # The fact stream keeps its operator-side XTRIM; no publish-time cap.
    assert by_topic["info.changes"].maxlen is None


@pytest.mark.asyncio
async def test_run_never_trims_excluded_topics(session_factory, publisher, fake_redis, monkeypatch):
    """The trim loop applies one global MAXLEN to every seen topic - sized for
    info.changes. A replay-from-0-0 stream subjected to it silently loses its
    convergence floor, so info.registry must be excluded even after its deltas
    put it in seen_topics."""
    trim_calls: set[tuple[str, int]] = set()

    async def _fake_trim(client, topic, maxlen):
        trim_calls.add((topic, maxlen))

    async def _fake_drain(*, seen_topics=None, **_kwargs):
        if seen_topics is not None:
            seen_topics.update({"info.changes", "info.registry"})
        return 0

    monkeypatch.setattr(publisher_mod, "trim_stream", _fake_trim)
    monkeypatch.setattr(publisher_mod, "drain_once", _fake_drain)

    stop = asyncio.Event()

    async def _stop_soon():
        await asyncio.sleep(0.05)
        stop.set()

    await asyncio.gather(
        publisher_mod.run(
            session_factory=session_factory,
            publisher=publisher,
            redis_client=fake_redis,
            stream_maxlen=100,
            trim_interval_iterations=1,
            stop_event=stop,
            active_interval=0.001,
            idle_interval=0.001,
            no_trim_topics=frozenset({"info.registry"}),
        ),
        _stop_soon(),
    )

    assert ("info.changes", 100) in trim_calls
    assert all(topic != "info.registry" for topic, _ in trim_calls)


# ---------------------------------------------------------------------------
# Periodic outbox stats log (archiver#112)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_emits_stats_on_cadence(session_factory, publisher, monkeypatch):
    """With a stats interval configured, the loop emits the periodic stats line
    (first iteration immediately, then on cadence)."""
    stats_calls: list[object] = []

    async def _fake_stats(factory):
        stats_calls.append(factory)

    monkeypatch.setattr(publisher_mod, "log_outbox_stats", _fake_stats)

    stop = asyncio.Event()

    async def _drain(**_kwargs):
        stop.set()
        return 0

    monkeypatch.setattr(publisher_mod, "drain_once", _drain)

    await publisher_mod.run(
        session_factory=session_factory,
        publisher=publisher,
        idle_interval=0.001,
        active_interval=0.001,
        stop_event=stop,
        stats_interval=0.0,
    )

    assert stats_calls == [session_factory]


@pytest.mark.asyncio
async def test_run_stats_disabled_with_none_interval(session_factory, publisher, monkeypatch):
    """stats_interval=None disables the periodic line entirely."""
    stats_calls: list[object] = []

    async def _fake_stats(factory):
        stats_calls.append(factory)

    monkeypatch.setattr(publisher_mod, "log_outbox_stats", _fake_stats)

    stop = asyncio.Event()

    async def _drain(**_kwargs):
        stop.set()
        return 0

    monkeypatch.setattr(publisher_mod, "drain_once", _drain)

    await publisher_mod.run(
        session_factory=session_factory,
        publisher=publisher,
        idle_interval=0.001,
        active_interval=0.001,
        stop_event=stop,
        stats_interval=None,
    )

    assert stats_calls == []


@pytest.mark.asyncio
async def test_run_stats_respects_interval_between_iterations(
    session_factory, publisher, monkeypatch
):
    """A long interval emits once (the immediate first line), not per-iteration."""
    stats_calls: list[object] = []

    async def _fake_stats(factory):
        stats_calls.append(factory)

    monkeypatch.setattr(publisher_mod, "log_outbox_stats", _fake_stats)

    stop = asyncio.Event()
    iterations = 0

    async def _drain(**_kwargs):
        nonlocal iterations
        iterations += 1
        if iterations >= 3:
            stop.set()
        return 0

    monkeypatch.setattr(publisher_mod, "drain_once", _drain)

    await publisher_mod.run(
        session_factory=session_factory,
        publisher=publisher,
        idle_interval=0.001,
        active_interval=0.001,
        stop_event=stop,
        stats_interval=3600.0,
    )

    assert iterations == 3
    assert len(stats_calls) == 1


# ---------------------------------------------------------------------------
# Periodic outbox prune (archiver#189)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_prunes_on_cadence(session_factory, publisher, monkeypatch):
    """With a retention window configured, the loop runs the retention pass
    (first iteration immediately, then on cadence) - the third periodic
    side-job riding the drain, after the XTRIM and the stats line."""
    prune_calls: list[tuple[object, int | None]] = []

    async def _fake_prune(factory, *, retention_days):
        prune_calls.append((factory, retention_days))

    monkeypatch.setattr(publisher_mod, "prune_outbox", _fake_prune)

    stop = asyncio.Event()

    async def _drain(**_kwargs):
        stop.set()
        return 0

    monkeypatch.setattr(publisher_mod, "drain_once", _drain)

    await publisher_mod.run(
        session_factory=session_factory,
        publisher=publisher,
        idle_interval=0.001,
        active_interval=0.001,
        stop_event=stop,
        stats_interval=None,
        retention_days=30,
        prune_interval=0.0,
    )

    assert prune_calls == [(session_factory, 30)]


@pytest.mark.asyncio
async def test_run_does_not_prune_without_retention(session_factory, publisher, monkeypatch):
    """retention_days=None (the disabled knob, and the default) prunes nothing."""
    prune_calls: list[object] = []

    async def _fake_prune(factory, *, retention_days):
        prune_calls.append(factory)

    monkeypatch.setattr(publisher_mod, "prune_outbox", _fake_prune)

    stop = asyncio.Event()

    async def _drain(**_kwargs):
        stop.set()
        return 0

    monkeypatch.setattr(publisher_mod, "drain_once", _drain)

    await publisher_mod.run(
        session_factory=session_factory,
        publisher=publisher,
        idle_interval=0.001,
        active_interval=0.001,
        stop_event=stop,
        stats_interval=None,
    )

    assert prune_calls == []


@pytest.mark.asyncio
async def test_run_prune_respects_interval_between_iterations(
    session_factory, publisher, monkeypatch
):
    """A long interval prunes once (the immediate first pass), not per-iteration -
    the pass is housekeeping, not part of the drain's hot path."""
    prune_calls: list[object] = []

    async def _fake_prune(factory, *, retention_days):
        prune_calls.append(factory)

    monkeypatch.setattr(publisher_mod, "prune_outbox", _fake_prune)

    stop = asyncio.Event()
    iterations = 0

    async def _drain(**_kwargs):
        nonlocal iterations
        iterations += 1
        if iterations >= 3:
            stop.set()
        return 0

    monkeypatch.setattr(publisher_mod, "drain_once", _drain)

    await publisher_mod.run(
        session_factory=session_factory,
        publisher=publisher,
        idle_interval=0.001,
        active_interval=0.001,
        stop_event=stop,
        stats_interval=None,
        retention_days=30,
        prune_interval=3600.0,
    )

    assert iterations == 3
    assert len(prune_calls) == 1
