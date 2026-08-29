"""ChangesOutboxRow model tests."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text

from src.core.models import ChangesOutboxRow


@pytest.mark.asyncio
async def test_round_trip(session):
    row = ChangesOutboxRow(
        topic="info.changes",
        payload={"event_type": "source_revision_captured", "info_source_id": "01HZZ"},
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    assert str(row.id)
    assert row.created_at is not None
    assert row.published_at is None
    assert row.publish_attempts == 0
    assert row.bus_message_id is None
    assert row.last_error is None


@pytest.mark.asyncio
async def test_published_state_round_trips(session):
    row = ChangesOutboxRow(topic="info.changes", payload={"x": 1})
    session.add(row)
    await session.commit()
    row.published_at = datetime.now(UTC)
    row.bus_message_id = "1735000000000-0"
    await session.commit()
    await session.refresh(row)
    assert row.bus_message_id == "1735000000000-0"
    assert row.published_at is not None


@pytest.mark.asyncio
async def test_unpublished_query_excludes_published(session):
    a = ChangesOutboxRow(topic="info.changes", payload={"n": 1})
    b = ChangesOutboxRow(topic="info.changes", payload={"n": 2})
    c = ChangesOutboxRow(topic="info.changes", payload={"n": 3})
    session.add_all([a, b, c])
    await session.commit()
    b.published_at = datetime.now(UTC)
    await session.commit()
    result = await session.execute(
        select(ChangesOutboxRow)
        .where(ChangesOutboxRow.published_at.is_(None))
        .order_by(ChangesOutboxRow.created_at)
    )
    rows = list(result.scalars())
    assert len(rows) == 2
    assert rows[0].id == a.id
    assert rows[1].id == c.id


@pytest.mark.asyncio
async def test_published_partial_index_backs_the_pruner(session):
    """The archiver#189 retention pass selects on ``published_at < cutoff``.
    Without a partial index over ``published_at IS NOT NULL`` that degrades to a
    seq scan of exactly the rows the pruner exists to bound - and the two
    pre-existing partial indexes both exclude published rows, so neither helps."""
    result = await session.execute(
        text(
            "SELECT indexname, indexdef FROM pg_indexes "
            "WHERE schemaname = 'information' AND tablename = 'changes_outbox'"
        )
    )
    indexes = {row[0]: row[1] for row in result.all()}
    assert "ix_changes_outbox_published" in indexes, "missing index ix_changes_outbox_published"
    definition = indexes["ix_changes_outbox_published"].lower()
    assert "published_at" in definition
    assert "where (published_at is not null)" in definition
