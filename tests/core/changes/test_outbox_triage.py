"""Tests for src/core/changes/outbox_triage - the exit from dead-lettered (archiver#191).

A dead-lettered outbox row had no way out: nothing cleared ``dead_lettered_at``,
so the #112 warning could never be acknowledged and an operator-fixed row could
never be republished. Two operations, both by explicit row id: discard (delete,
logged in full first) and rearm (back into the drain's queue, guarded).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker
from ulid import ULID

from src.core.changes import outbox_triage
from src.core.changes.outbox_triage import (
    REARMABLE_TOPICS,
    discard_dead_lettered,
    list_dead_lettered,
    rearm_dead_lettered,
)
from src.core.models import ChangesOutboxRow

_T0 = datetime(2026, 9, 1, 12, 0, 0, tzinfo=UTC)


def _captured_event(source_revision_id: str = "rev-1") -> dict:
    """A full, publishable ``source_revision_captured`` payload."""
    return {
        "schema_version": 2,
        "event_type": "source_revision_captured",
        "occurred_at": "2026-07-28T12:00:00+00:00",
        "info_source_id": "01HZZ000000000000000000001",
        "source_revision_id": source_revision_id,
        "content_fingerprint": "sha256:" + "a" * 64,
        "bindings": [{"info_item_id": "01HZZ000000000000000000003"}],
    }


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


async def _insert(
    session_factory,
    *,
    topic: str = "info.changes",
    payload: dict | None = None,
    dead_lettered_at: datetime | None = _T0,
    published_at: datetime | None = None,
    publish_attempts: int = 100_000,
    last_error: str | None = "WRONGTYPE Operation against a key holding the wrong kind",
) -> ChangesOutboxRow:
    async with session_factory() as session:
        row = ChangesOutboxRow(
            topic=topic,
            payload=payload if payload is not None else _captured_event(),
            dead_lettered_at=dead_lettered_at,
            published_at=published_at,
            publish_attempts=publish_attempts,
            last_error=last_error,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row


async def _get(session_factory, row_id: ULID) -> ChangesOutboxRow | None:
    async with session_factory() as session:
        return (
            await session.execute(select(ChangesOutboxRow).where(ChangesOutboxRow.id == row_id))
        ).scalar_one_or_none()


# ---------------------------------------------------------------------------
# list_dead_lettered
# ---------------------------------------------------------------------------


async def test_list_returns_only_dead_lettered_rows_oldest_first(session_factory):
    later = await _insert(session_factory, dead_lettered_at=_T0 + timedelta(minutes=5))
    earlier = await _insert(session_factory, dead_lettered_at=_T0)
    await _insert(session_factory, dead_lettered_at=None)  # live
    await _insert(session_factory, dead_lettered_at=None, published_at=_T0)  # published

    async with session_factory() as session:
        rows, has_more = await list_dead_lettered(session, limit=10, offset=0)

    assert [r.id for r in rows] == [earlier.id, later.id]
    assert has_more is False


async def test_list_pages_with_has_more(session_factory):
    for i in range(3):
        await _insert(session_factory, dead_lettered_at=_T0 + timedelta(minutes=i))

    async with session_factory() as session:
        first, more_first = await list_dead_lettered(session, limit=2, offset=0)
        second, more_second = await list_dead_lettered(session, limit=2, offset=2)

    assert len(first) == 2 and more_first is True
    assert len(second) == 1 and more_second is False


# ---------------------------------------------------------------------------
# discard_dead_lettered
# ---------------------------------------------------------------------------


async def test_discard_deletes_the_named_dead_lettered_row(session_factory):
    row = await _insert(session_factory)
    keep = await _insert(session_factory)

    async with session_factory() as session:
        outcome = await discard_dead_lettered(session, [str(row.id)])

    assert outcome.discarded == [str(row.id)]
    assert outcome.not_found == []
    assert await _get(session_factory, row.id) is None
    assert await _get(session_factory, keep.id) is not None


async def test_discard_never_deletes_a_live_or_published_row(session_factory):
    """The guard is the query's own: only a dead-lettered row is discardable."""
    live = await _insert(session_factory, dead_lettered_at=None, publish_attempts=0)
    published = await _insert(
        session_factory, dead_lettered_at=None, published_at=_T0, publish_attempts=0
    )

    async with session_factory() as session:
        outcome = await discard_dead_lettered(session, [str(live.id), str(published.id)])

    assert outcome.discarded == []
    assert outcome.not_found == [str(live.id), str(published.id)]
    assert await _get(session_factory, live.id) is not None
    assert await _get(session_factory, published.id) is not None


async def test_discard_reports_unknown_ids_as_not_found(session_factory):
    missing = str(ULID())
    async with session_factory() as session:
        outcome = await discard_dead_lettered(session, [missing])
    assert outcome.discarded == []
    assert outcome.not_found == [missing]


async def test_discard_dedupes_repeated_ids_in_request_order(session_factory):
    a = await _insert(session_factory)
    b = await _insert(session_factory)
    async with session_factory() as session:
        outcome = await discard_dead_lettered(session, [str(b.id), str(a.id), str(b.id)])
    assert outcome.discarded == [str(b.id), str(a.id)]


async def test_discard_logs_the_full_row_before_deleting(session_factory):
    """journald keeps ~2 weeks here, so the dead-letter-time ERROR line may be
    gone by triage; the discard writes its own record of what it deleted.

    Spies the module logger rather than using ``caplog``: another test in the
    suite runs ``configure_logging()``, after which ``caplog`` misses the record
    (the ``test_dlq_triage`` precedent)."""
    row = await _insert(session_factory, topic="info.changes")

    with patch.object(outbox_triage.logger, "info") as info:
        async with session_factory() as session:
            await discard_dead_lettered(session, [str(row.id)])

    [call] = info.call_args_list
    assert call.args == ("Discarding dead-lettered outbox row",)
    extra = call.kwargs["extra"]
    assert extra["row_id"] == str(row.id)
    assert extra["topic"] == "info.changes"
    assert extra["payload"] == _captured_event()
    assert extra["last_error"] == row.last_error
    assert extra["publish_attempts"] == row.publish_attempts
    assert extra["dead_lettered_at"] == _T0.isoformat()


async def test_a_failed_discard_logs_that_it_rolled_back(session_factory):
    """The per-row ``Discarding`` lines precede the commit. If the commit fails
    nothing was deleted, and journald must say so rather than stand as the
    record of a discard that never happened."""
    row = await _insert(session_factory)

    with patch.object(outbox_triage.logger, "warning") as warning:
        async with session_factory() as session:
            with (
                patch.object(session, "commit", side_effect=RuntimeError("db gone")),
                pytest.raises(RuntimeError),
            ):
                await discard_dead_lettered(session, [str(row.id)])

    [call] = warning.call_args_list
    assert call.args == ("Discard of dead-lettered outbox rows rolled back",)
    assert call.kwargs["extra"]["row_ids"] == [str(row.id)]
    assert await _get(session_factory, row.id) is not None


# ---------------------------------------------------------------------------
# rearm_dead_lettered
# ---------------------------------------------------------------------------


async def test_rearm_returns_a_publishable_row_to_the_drain_queue(session_factory):
    row = await _insert(session_factory)

    async with session_factory() as session:
        [result] = await rearm_dead_lettered(session, [str(row.id)])

    assert result.row_id == str(row.id)
    assert result.outcome == "rearmed"
    assert result.detail is None
    after = await _get(session_factory, row.id)
    assert after.dead_lettered_at is None
    assert after.publish_attempts == 0
    assert after.published_at is None


async def test_rearm_rejects_a_row_that_still_does_not_build(session_factory):
    """Build-phase poison is deterministic: re-arming it would only re-dead-letter
    it on the next drain. The pure build step runs first and leaves it alone."""
    row = await _insert(session_factory, payload={"event_type": "who_knows"})

    async with session_factory() as session:
        [result] = await rearm_dead_lettered(session, [str(row.id)])

    assert result.outcome == "rejected"
    assert result.detail
    after = await _get(session_factory, row.id)
    assert after.dead_lettered_at == _T0
    assert after.publish_attempts == 100_000


@pytest.mark.parametrize("topic", ["info.registry", "content.replicate"])
async def test_rearm_refuses_topics_where_a_late_publish_is_wrong(session_factory, topic):
    """info.registry: the hourly snapshot is the repair. content.replicate: the
    reaper may have abandoned the command; re-issuing is #171's, with a fresh id."""
    row = await _insert(session_factory, topic=topic)

    async with session_factory() as session:
        [result] = await rearm_dead_lettered(session, [str(row.id)])

    assert result.outcome == "refused"
    assert topic in result.detail
    after = await _get(session_factory, row.id)
    assert after.dead_lettered_at == _T0


def test_only_the_fact_stream_is_rearmable():
    assert REARMABLE_TOPICS == frozenset({"info.changes"})


async def test_rearm_reports_live_and_unknown_rows_as_not_found(session_factory):
    live = await _insert(session_factory, dead_lettered_at=None, publish_attempts=3)
    missing = str(ULID())

    async with session_factory() as session:
        results = await rearm_dead_lettered(session, [str(live.id), missing])

    assert [(r.row_id, r.outcome) for r in results] == [
        (str(live.id), "not_found"),
        (missing, "not_found"),
    ]
    assert (await _get(session_factory, live.id)).publish_attempts == 3


async def test_rearm_logs_each_rearmed_row(session_factory):
    """The attempts and error the rearm wipes are recorded before it wipes them."""
    row = await _insert(session_factory)

    with patch.object(outbox_triage.logger, "info") as info:
        async with session_factory() as session:
            await rearm_dead_lettered(session, [str(row.id)])

    [call] = info.call_args_list
    assert call.args == ("Re-arming dead-lettered outbox row",)
    extra = call.kwargs["extra"]
    assert extra["row_id"] == str(row.id)
    assert extra["last_error"] == row.last_error
    assert extra["publish_attempts"] == row.publish_attempts
