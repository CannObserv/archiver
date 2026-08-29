"""Tests for src/core/changes/outbox_prune - published-row retention (archiver#189).

The outbox is the producer-side delivery guarantee; once a row is published its
only residual value is forensic (``bus_message_id`` correlation), so it is
prunable. Two states are never prunable: a live row (the drain's own queue) and
a dead-lettered row (the archiver#107 post-mortem record).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.core.changes import outbox_prune as outbox_prune_mod
from src.core.changes.outbox_prune import (
    DEFAULT_PRUNE_BATCH_SIZE,
    DEFAULT_RETENTION_DAYS,
    MAX_PRUNE_BATCHES,
    prune_outbox,
    prune_published_rows,
    resolve_retention_days,
)
from src.core.models import ChangesOutboxRow

_NOW = datetime(2026, 8, 29, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
async def session_factory(test_engine):
    """Independent sessions (no SAVEPOINT wrap) - same shape as the publisher tests."""
    return async_sessionmaker(bind=test_engine, expire_on_commit=False)


@pytest.fixture(autouse=True)
async def cleanup_outbox(test_engine):
    """Truncate the outbox table before and after each test."""
    async with test_engine.begin() as conn:
        await conn.execute(text("TRUNCATE TABLE information.changes_outbox"))
    yield
    async with test_engine.begin() as conn:
        await conn.execute(text("TRUNCATE TABLE information.changes_outbox"))


async def _insert_row(
    session_factory,
    *,
    created_at: datetime,
    published_at: datetime | None = None,
    dead_lettered_at: datetime | None = None,
) -> ChangesOutboxRow:
    async with session_factory() as session:
        row = ChangesOutboxRow(
            topic="info.changes",
            payload={"event_type": "irrelevant"},
            created_at=created_at,
            published_at=published_at,
            dead_lettered_at=dead_lettered_at,
        )
        session.add(row)
        await session.commit()
        return row


async def _row_count(session_factory) -> int:
    async with session_factory() as session:
        return (
            await session.execute(select(func.count()).select_from(ChangesOutboxRow))
        ).scalar_one()


# ---------------------------------------------------------------------------
# resolve_retention_days - same parse contract as resolve_stream_maxlen
# ---------------------------------------------------------------------------


def test_resolve_retention_unset_uses_default():
    assert resolve_retention_days(None) == DEFAULT_RETENTION_DAYS


def test_resolve_retention_parses_positive_value():
    assert resolve_retention_days("7") == 7


@pytest.mark.parametrize("raw", ["0", "-1"])
def test_resolve_retention_non_positive_disables(raw):
    assert resolve_retention_days(raw) is None


def test_resolve_retention_invalid_falls_back_to_default(monkeypatch):
    """Malformed must never raise: main.lifespan resolves this inside the broad
    guard that would otherwise disable the whole publisher over a typo."""
    warnings: list[str] = []
    monkeypatch.setattr(
        outbox_prune_mod.logger, "warning", lambda msg, *a, **k: warnings.append(msg)
    )

    assert resolve_retention_days("thirty") == DEFAULT_RETENTION_DAYS
    assert warnings == ["Invalid ARCHIVER_OUTBOX_RETENTION_DAYS; falling back to default"]


# ---------------------------------------------------------------------------
# prune_published_rows - the predicate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prunes_published_rows_older_than_cutoff(session_factory):
    old = await _insert_row(
        session_factory,
        created_at=_NOW - timedelta(days=40),
        published_at=_NOW - timedelta(days=40),
    )
    async with session_factory() as session:
        deleted = await prune_published_rows(session, retention_days=30, now=_NOW)

    assert deleted == 1
    async with session_factory() as session:
        remaining = (await session.execute(select(ChangesOutboxRow.id))).scalars().all()
    assert old.id not in remaining
    assert remaining == []


@pytest.mark.asyncio
async def test_keeps_published_rows_inside_the_window(session_factory):
    await _insert_row(
        session_factory,
        created_at=_NOW - timedelta(days=3),
        published_at=_NOW - timedelta(days=3),
    )
    async with session_factory() as session:
        deleted = await prune_published_rows(session, retention_days=30, now=_NOW)

    assert deleted == 0
    assert await _row_count(session_factory) == 1


@pytest.mark.asyncio
async def test_never_prunes_live_rows(session_factory):
    """A live row is the drain's own queue - age is irrelevant, and an ancient
    unpublished row is exactly the backlog the #112 stats exist to surface."""
    await _insert_row(session_factory, created_at=_NOW - timedelta(days=400))
    async with session_factory() as session:
        deleted = await prune_published_rows(session, retention_days=30, now=_NOW)

    assert deleted == 0
    assert await _row_count(session_factory) == 1


@pytest.mark.asyncio
async def test_never_prunes_dead_lettered_rows(session_factory):
    """Dead-lettered rows are the archiver#107 post-mortem record and the #112
    danger signal. The row here is deliberately constructed in a state the
    publisher cannot produce (published AND dead-lettered) to pin the explicit
    clause rather than the emergent property."""
    await _insert_row(
        session_factory,
        created_at=_NOW - timedelta(days=400),
        published_at=_NOW - timedelta(days=400),
        dead_lettered_at=_NOW - timedelta(days=400),
    )
    async with session_factory() as session:
        deleted = await prune_published_rows(session, retention_days=30, now=_NOW)

    assert deleted == 0
    assert await _row_count(session_factory) == 1


@pytest.mark.asyncio
async def test_prune_is_bounded_per_invocation(session_factory):
    """Batched and capped: the first prune against a table that has grown for a
    year must not be one unbounded DELETE. The remainder waits for the next tick."""
    for _ in range(5):
        await _insert_row(
            session_factory,
            created_at=_NOW - timedelta(days=40),
            published_at=_NOW - timedelta(days=40),
        )
    async with session_factory() as session:
        deleted = await prune_published_rows(
            session, retention_days=30, now=_NOW, batch_size=2, max_batches=2
        )

    assert deleted == 4
    assert await _row_count(session_factory) == 1


@pytest.mark.asyncio
async def test_prune_stops_early_when_batch_is_short(session_factory):
    """A short batch means the queue is drained; no further round trips."""
    await _insert_row(
        session_factory,
        created_at=_NOW - timedelta(days=40),
        published_at=_NOW - timedelta(days=40),
    )
    async with session_factory() as session:
        deleted = await prune_published_rows(
            session, retention_days=30, now=_NOW, batch_size=100, max_batches=10
        )

    assert deleted == 1
    assert await _row_count(session_factory) == 0


def test_prune_bounds_are_sane():
    """The per-invocation ceiling has to dwarf any plausible accrual between
    ticks, or the backlog outruns the pruner."""
    assert DEFAULT_PRUNE_BATCH_SIZE * MAX_PRUNE_BATCHES >= 10_000


# ---------------------------------------------------------------------------
# prune_outbox - the loop-facing wrapper
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prune_outbox_deletes_and_logs(session_factory, monkeypatch):
    infos: list[dict] = []
    monkeypatch.setattr(
        outbox_prune_mod.logger, "info", lambda *a, **k: infos.append(k.get("extra", {}))
    )
    await _insert_row(
        session_factory,
        created_at=_NOW - timedelta(days=40),
        published_at=_NOW - timedelta(days=40),
    )

    await prune_outbox(session_factory, retention_days=30, now=_NOW)

    assert await _row_count(session_factory) == 0
    assert infos == [{"deleted": 1, "retention_days": 30, "capped": False}]


@pytest.mark.asyncio
async def test_prune_outbox_silent_when_nothing_deleted(session_factory, monkeypatch):
    """Nothing to prune is the healthy steady state; it must not log every tick."""
    infos: list[dict] = []
    monkeypatch.setattr(
        outbox_prune_mod.logger, "info", lambda *a, **k: infos.append(k.get("extra", {}))
    )
    await _insert_row(session_factory, created_at=_NOW - timedelta(days=1))

    await prune_outbox(session_factory, retention_days=30, now=_NOW)

    assert infos == []


@pytest.mark.asyncio
async def test_prune_outbox_disabled_by_none_retention(session_factory):
    await _insert_row(
        session_factory,
        created_at=_NOW - timedelta(days=400),
        published_at=_NOW - timedelta(days=400),
    )

    await prune_outbox(session_factory, retention_days=None, now=_NOW)

    assert await _row_count(session_factory) == 1


@pytest.mark.asyncio
async def test_prune_outbox_swallows_failures(monkeypatch):
    """Pure housekeeping riding the drain loop: a failure here can never be
    allowed to take down the publisher."""
    warnings: list[str] = []
    monkeypatch.setattr(
        outbox_prune_mod.logger, "warning", lambda msg, *a, **k: warnings.append(msg)
    )

    def _exploding_factory():
        raise RuntimeError("database is on fire")

    await prune_outbox(_exploding_factory, retention_days=30, now=_NOW)

    assert warnings == ["Outbox prune failed"]
