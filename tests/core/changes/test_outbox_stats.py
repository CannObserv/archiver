"""Tests for src/core/changes/outbox_stats - producer-side outbox observability (archiver#112).

Three numbers, computed on request from cheap indexed queries:
``unpublished_count`` and ``oldest_unpublished_age_seconds`` over the drain
loop's exact live predicate (published_at IS NULL AND dead_lettered_at IS NULL),
and ``dead_lettered_count`` over the terminal rows archiver#107 introduced.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.core.changes import outbox_stats as outbox_stats_mod
from src.core.changes.outbox_stats import OutboxStats, collect_outbox_stats, log_outbox_stats
from src.core.models import ChangesOutboxRow

_NOW = datetime(2026, 8, 27, 12, 0, 0, tzinfo=UTC)


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


@pytest.mark.asyncio
async def test_empty_outbox_reports_zeroes(session_factory):
    async with session_factory() as session:
        stats = await collect_outbox_stats(session, now=_NOW)
    assert stats == OutboxStats(
        unpublished_count=0,
        oldest_unpublished_age_seconds=None,
        dead_lettered_count=0,
    )


@pytest.mark.asyncio
async def test_counts_partition_by_row_state(session_factory):
    """Live rows count as unpublished; published and dead-lettered rows do not,
    and dead-lettered rows are counted separately."""
    await _insert_row(session_factory, created_at=_NOW - timedelta(seconds=30))
    await _insert_row(session_factory, created_at=_NOW - timedelta(seconds=20))
    await _insert_row(
        session_factory,
        created_at=_NOW - timedelta(hours=2),
        published_at=_NOW - timedelta(hours=1),
    )
    await _insert_row(
        session_factory,
        created_at=_NOW - timedelta(hours=3),
        dead_lettered_at=_NOW - timedelta(hours=2),
    )

    async with session_factory() as session:
        stats = await collect_outbox_stats(session, now=_NOW)

    assert stats.unpublished_count == 2
    assert stats.dead_lettered_count == 1
    # Oldest LIVE row is 30s old - the 3h-old dead-lettered row must not leak
    # into the age, or a retired poison row would look like a wedged backlog.
    assert stats.oldest_unpublished_age_seconds == pytest.approx(30.0)


@pytest.mark.asyncio
async def test_age_clamped_to_zero_for_future_created_at(session_factory):
    """Clock skew between app and DB must not produce a negative age."""
    await _insert_row(session_factory, created_at=_NOW + timedelta(seconds=5))
    async with session_factory() as session:
        stats = await collect_outbox_stats(session, now=_NOW)
    assert stats.oldest_unpublished_age_seconds == 0.0


@pytest.mark.asyncio
async def test_log_outbox_stats_info_when_healthy(session_factory, monkeypatch):
    await _insert_row(session_factory, created_at=_NOW - timedelta(seconds=10))

    infos: list[dict] = []
    warnings: list[dict] = []
    monkeypatch.setattr(
        outbox_stats_mod.logger, "info", lambda *a, **k: infos.append(k.get("extra", {}))
    )
    monkeypatch.setattr(
        outbox_stats_mod.logger, "warning", lambda *a, **k: warnings.append(k.get("extra", {}))
    )

    await log_outbox_stats(session_factory)

    assert warnings == []
    assert len(infos) == 1
    assert infos[0]["unpublished_count"] == 1
    assert infos[0]["dead_lettered_count"] == 0
    assert infos[0]["oldest_unpublished_age_seconds"] is not None


@pytest.mark.asyncio
async def test_log_outbox_stats_warns_when_dead_lettered(session_factory, monkeypatch):
    """A retired poison row keeps a periodic WARNING alive - the one-time ERROR
    at dead-letter time is otherwise the only trace (the archiver#109 incident)."""
    await _insert_row(session_factory, created_at=_NOW, dead_lettered_at=_NOW)

    warnings: list[dict] = []
    monkeypatch.setattr(
        outbox_stats_mod.logger, "warning", lambda *a, **k: warnings.append(k.get("extra", {}))
    )

    await log_outbox_stats(session_factory)

    assert len(warnings) == 1
    assert warnings[0]["dead_lettered_count"] == 1


@pytest.mark.asyncio
async def test_log_outbox_stats_swallows_collection_failure(monkeypatch):
    """Stats are observability - a failure must log and return, never propagate
    into (and crash) the publisher drain loop."""

    def broken_factory():
        raise RuntimeError("db down")

    warnings: list[str] = []
    monkeypatch.setattr(
        outbox_stats_mod.logger, "warning", lambda msg, *a, **k: warnings.append(msg)
    )

    await log_outbox_stats(broken_factory)

    assert len(warnings) == 1
