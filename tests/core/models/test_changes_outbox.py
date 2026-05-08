"""ChangesOutboxRow model tests."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

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
