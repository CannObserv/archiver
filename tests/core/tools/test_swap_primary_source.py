"""Tests for the swap_primary_source core tool (archiver#45)."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from ulid import ULID

from src.core.models import ChangesOutboxRow, InfoItem, InfoItemSource, InfoSource
from src.core.tools.swap_primary_source import (
    InfoItemNotFoundError,
    InfoSourceNotFoundError,
    swap_primary_source,
)


def _spec() -> dict:
    return {
        "schema_version": 1,
        "extraction": {"algorithm": "full_page"},
        "fingerprint": {},
    }


@pytest.fixture
async def item(session):
    obj = InfoItem(name="t")
    session.add(obj)
    await session.flush()
    return obj


async def _source(session, url: str) -> InfoSource:
    src = InfoSource(url=url, source_specs=[_spec()])
    session.add(src)
    await session.flush()
    return src


async def _bind(session, item, src, *, deactivated: bool = False) -> InfoItemSource:
    binding = InfoItemSource(
        info_item_id=item.info_item_id,
        info_source_id=src.info_source_id,
        deactivated_at=datetime.now(UTC) if deactivated else None,
    )
    session.add(binding)
    await session.flush()
    return binding


async def _outbox(session, topic: str) -> list[dict]:
    result = await session.execute(
        select(ChangesOutboxRow.payload).where(ChangesOutboxRow.topic == topic)
    )
    return list(result.scalars())


async def _primary_changed(session) -> list[dict]:
    return [
        p
        for p in await _outbox(session, "info.changes")
        if p.get("event_type") == "info_item_primary_changed"
    ]


async def _active(session, item) -> list[InfoItemSource]:
    result = await session.execute(
        select(InfoItemSource).where(
            InfoItemSource.info_item_id == item.info_item_id,
            InfoItemSource.deactivated_at.is_(None),
        )
    )
    return list(result.scalars())


# --- replacement ---


@pytest.mark.asyncio
async def test_swap_deactivates_old_and_binds_new(session, item):
    old = await _source(session, "https://example.com/a")
    new = await _source(session, "https://example.com/b")
    old_binding = await _bind(session, item, old)

    result = await swap_primary_source(
        session, info_item_id=item.info_item_id, info_source_id=new.info_source_id
    )

    assert result.binding.info_source_id == new.info_source_id
    assert result.binding.deactivated_at is None
    assert result.previous_info_source_id == old.info_source_id
    assert result.changed is True
    assert old_binding.deactivated_at is not None
    assert [b.info_source_id for b in await _active(session, item)] == [new.info_source_id]


@pytest.mark.asyncio
async def test_swap_announces_once_with_the_final_state(session, item):
    """One announcement for deactivate + bind: two would be revoked-then-live."""
    old = await _source(session, "https://example.com/a")
    new = await _source(session, "https://example.com/b")
    await _bind(session, item, old)

    await swap_primary_source(
        session, info_item_id=item.info_item_id, info_source_id=new.info_source_id
    )

    rows = await _outbox(session, "info.registry")
    assert len(rows) == 1
    assert rows[0]["revoked"] is False
    assert rows[0]["info_source_id"] == str(new.info_source_id)


@pytest.mark.asyncio
async def test_swap_emits_primary_changed_with_old_and_new(session, item):
    old = await _source(session, "https://example.com/a")
    new = await _source(session, "https://example.com/b")
    await _bind(session, item, old)

    await swap_primary_source(
        session, info_item_id=item.info_item_id, info_source_id=new.info_source_id
    )

    events = await _primary_changed(session)
    assert len(events) == 1
    assert events[0]["info_item_id"] == str(item.info_item_id)
    assert events[0]["old_info_source_id"] == str(old.info_source_id)
    assert events[0]["new_info_source_id"] == str(new.info_source_id)


# --- first assignment ---


@pytest.mark.asyncio
async def test_swap_with_no_active_primary_binds(session, item):
    new = await _source(session, "https://example.com/b")

    result = await swap_primary_source(
        session, info_item_id=item.info_item_id, info_source_id=new.info_source_id
    )

    assert result.previous_info_source_id is None
    assert result.changed is True
    events = await _primary_changed(session)
    assert len(events) == 1
    assert events[0]["old_info_source_id"] is None


# --- no-op ---


@pytest.mark.asyncio
async def test_swap_to_the_current_primary_is_a_no_op(session, item):
    """Re-PUTting the current primary writes nothing and announces nothing."""
    src = await _source(session, "https://example.com/a")
    binding = await _bind(session, item, src)

    result = await swap_primary_source(
        session, info_item_id=item.info_item_id, info_source_id=src.info_source_id
    )

    assert result.changed is False
    assert result.binding is binding
    assert binding.deactivated_at is None
    assert result.previous_info_source_id == src.info_source_id
    assert await _outbox(session, "info.registry") == []
    assert await _primary_changed(session) == []


# --- refusals ---


@pytest.mark.asyncio
async def test_unknown_item_raises(session):
    src = await _source(session, "https://example.com/a")
    with pytest.raises(InfoItemNotFoundError):
        await swap_primary_source(session, info_item_id=ULID(), info_source_id=src.info_source_id)


@pytest.mark.asyncio
async def test_unknown_source_raises_and_leaves_the_primary(session, item):
    old = await _source(session, "https://example.com/a")
    old_binding = await _bind(session, item, old)

    with pytest.raises(InfoSourceNotFoundError):
        await swap_primary_source(session, info_item_id=item.info_item_id, info_source_id=ULID())

    assert old_binding.deactivated_at is None
    assert await _outbox(session, "info.registry") == []


@pytest.mark.asyncio
async def test_a_previous_primary_is_reactivated(session, item):
    """The (item, source) key holds the history row, so a revert reactivates it."""
    earlier = await _source(session, "https://example.com/a")
    current = await _source(session, "https://example.com/b")
    earlier_binding = await _bind(session, item, earlier, deactivated=True)
    current_binding = await _bind(session, item, current)

    result = await swap_primary_source(
        session, info_item_id=item.info_item_id, info_source_id=earlier.info_source_id
    )

    assert result.binding is earlier_binding
    assert result.changed is True
    assert result.previous_info_source_id == current.info_source_id
    assert earlier_binding.deactivated_at is None
    assert current_binding.deactivated_at is not None
    assert [b.info_source_id for b in await _active(session, item)] == [earlier.info_source_id]
    registry = await _outbox(session, "info.registry")
    assert len(registry) == 1
    assert registry[0]["info_source_id"] == str(earlier.info_source_id)
    events = await _primary_changed(session)
    assert len(events) == 1
    assert events[0]["old_info_source_id"] == str(current.info_source_id)
    assert events[0]["new_info_source_id"] == str(earlier.info_source_id)


@pytest.mark.asyncio
async def test_a_previous_primary_is_reactivated_when_there_is_no_current_one(session, item):
    earlier = await _source(session, "https://example.com/a")
    earlier_binding = await _bind(session, item, earlier, deactivated=True)

    result = await swap_primary_source(
        session, info_item_id=item.info_item_id, info_source_id=earlier.info_source_id
    )

    assert result.binding is earlier_binding
    assert result.previous_info_source_id is None
    assert earlier_binding.deactivated_at is None
