"""Tests for the bind_info_source core tool."""

import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker
from ulid import ULID

from src.core.models import ChangesOutboxRow, InfoItem, InfoItemSource, InfoSource
from src.core.tools.bind_info_source import (
    ActiveBindingAlreadyExistsError,
    InfoItemNotFoundError,
    InfoSourceNotFoundError,
    bind_info_source,
)
from src.core.tools.rep_fields_gate import lock_info_item


def _spec(algorithm: str = "full_page") -> dict:
    doc: dict = {
        "schema_version": 1,
        "extraction": {"algorithm": algorithm},
        "fingerprint": {},
    }
    if algorithm != "full_page":
        doc["extraction"]["selector"] = "#x"
    return doc


@pytest.fixture
async def item(session):
    obj = InfoItem(name="t")
    session.add(obj)
    await session.flush()
    return obj


@pytest.fixture
async def source(session):
    src = InfoSource(url="https://example.com/p", source_specs=[_spec()])
    session.add(src)
    await session.flush()
    return src


@pytest.fixture
async def other_source(session):
    src = InfoSource(url="https://example.com/q", source_specs=[_spec()])
    session.add(src)
    await session.flush()
    return src


# --- happy path ---


@pytest.mark.asyncio
async def test_bind_creates_active_binding(session, item, source):
    binding = await bind_info_source(
        session, info_item_id=item.info_item_id, info_source_id=source.info_source_id
    )
    assert binding.info_item_id == item.info_item_id
    assert binding.info_source_id == source.info_source_id
    assert binding.deactivated_at is None


@pytest.mark.asyncio
async def test_deactivated_binding_allows_new_active(session, item, source, other_source):
    old = InfoItemSource(
        info_item_id=item.info_item_id,
        info_source_id=source.info_source_id,
        deactivated_at=datetime.now(UTC),
    )
    session.add(old)
    await session.commit()
    binding = await bind_info_source(
        session, info_item_id=item.info_item_id, info_source_id=other_source.info_source_id
    )
    assert binding.deactivated_at is None


@pytest.mark.asyncio
async def test_binding_a_previous_primary_starts_a_new_tenure(session, item, source):
    """It used to collide with the history row on the composite key: a 500 (archiver#389)."""
    old = InfoItemSource(
        info_item_id=item.info_item_id,
        info_source_id=source.info_source_id,
        deactivated_at=datetime.now(UTC),
    )
    session.add(old)
    await session.flush()
    first_tenure_end = old.deactivated_at

    binding = await bind_info_source(
        session, info_item_id=item.info_item_id, info_source_id=source.info_source_id
    )

    assert binding.id != old.id
    assert binding.deactivated_at is None
    assert old.deactivated_at == first_tenure_end


# --- info_item_primary_changed: the tool emits, so no bind path can forget (archiver#390) ---


async def _primary_changed(session) -> list[dict]:
    payloads = (
        await session.execute(
            select(ChangesOutboxRow.payload).where(ChangesOutboxRow.topic == "info.changes")
        )
    ).scalars()
    return [p for p in payloads if p.get("event_type") == "info_item_primary_changed"]


@pytest.mark.asyncio
async def test_first_assignment_emits_once_with_no_old(session, item, source):
    await bind_info_source(
        session, info_item_id=item.info_item_id, info_source_id=source.info_source_id
    )

    events = await _primary_changed(session)
    assert len(events) == 1
    assert events[0]["info_item_id"] == str(item.info_item_id)
    assert events[0]["old_info_source_id"] is None
    assert events[0]["new_info_source_id"] == str(source.info_source_id)


@pytest.mark.asyncio
async def test_succession_emits_the_latest_closed_tenure_as_old(
    session, item, source, other_source
):
    """Two closed tenures: ``old`` is the one closed last, not the one opened first."""
    third = InfoSource(url="https://example.com/r", source_specs=[_spec()])
    session.add(third)
    await session.flush()
    session.add_all(
        [
            InfoItemSource(
                info_item_id=item.info_item_id,
                info_source_id=source.info_source_id,
                deactivated_at=datetime(2026, 1, 1, tzinfo=UTC),
            ),
            InfoItemSource(
                info_item_id=item.info_item_id,
                info_source_id=other_source.info_source_id,
                deactivated_at=datetime(2026, 2, 1, tzinfo=UTC),
            ),
        ]
    )
    await session.flush()

    await bind_info_source(
        session, info_item_id=item.info_item_id, info_source_id=third.info_source_id
    )

    events = await _primary_changed(session)
    assert len(events) == 1
    assert events[0]["old_info_source_id"] == str(other_source.info_source_id)
    assert events[0]["new_info_source_id"] == str(third.info_source_id)


@pytest.mark.asyncio
async def test_equal_close_times_break_the_tie_by_tenure_id(session, item, source, other_source):
    """Same ``deactivated_at``: the later tenure (the larger ULID ``id``) is ``old`` (CR 3)."""
    third = InfoSource(url="https://example.com/r", source_specs=[_spec()])
    session.add(third)
    await session.flush()
    closed = datetime(2026, 3, 1, tzinfo=UTC)
    earlier_id, later_id = sorted([ULID(), ULID()])
    # The earlier tenure goes in first, so heap order alone would pick it.
    for tenure_id, src in ((earlier_id, source), (later_id, other_source)):
        session.add(
            InfoItemSource(
                id=tenure_id,
                info_item_id=item.info_item_id,
                info_source_id=src.info_source_id,
                deactivated_at=closed,
            )
        )
        await session.flush()

    await bind_info_source(
        session, info_item_id=item.info_item_id, info_source_id=third.info_source_id
    )

    events = await _primary_changed(session)
    assert events[0]["old_info_source_id"] == str(other_source.info_source_id)


@pytest.mark.asyncio
async def test_a_refused_bind_emits_nothing(session, item, source, other_source):
    await bind_info_source(
        session, info_item_id=item.info_item_id, info_source_id=source.info_source_id
    )
    with pytest.raises(ActiveBindingAlreadyExistsError):
        await bind_info_source(
            session, info_item_id=item.info_item_id, info_source_id=other_source.info_source_id
        )
    with pytest.raises(InfoSourceNotFoundError):
        await bind_info_source(session, info_item_id=item.info_item_id, info_source_id=ULID())

    assert len(await _primary_changed(session)) == 1


# --- collision guard ---


@pytest.mark.asyncio
async def test_second_active_binding_rejected(session, item, source, other_source):
    await bind_info_source(
        session, info_item_id=item.info_item_id, info_source_id=source.info_source_id
    )
    with pytest.raises(ActiveBindingAlreadyExistsError) as exc_info:
        await bind_info_source(
            session, info_item_id=item.info_item_id, info_source_id=other_source.info_source_id
        )
    assert exc_info.value.existing_info_source_id == source.info_source_id


# --- existence ---


@pytest.mark.asyncio
async def test_unknown_info_item_rejected(session, source):
    with pytest.raises(InfoItemNotFoundError):
        await bind_info_source(session, info_item_id=ULID(), info_source_id=source.info_source_id)


@pytest.mark.asyncio
async def test_unknown_info_source_rejected(session, item):
    with pytest.raises(InfoSourceNotFoundError):
        await bind_info_source(session, info_item_id=item.info_item_id, info_source_id=ULID())


# --- concurrency: the InfoItem row serializes a bind against a swap ---


@pytest.mark.asyncio
async def test_a_bind_waits_for_a_swap_and_then_sees_its_primary(test_engine, committed_rows):
    """``swap_primary_source`` holds the item lock while it binds. Without the
    same lock here, both see no primary, and the later insert collides on
    ``uq_info_item_sources_active``: a 500 instead of the 409 (archiver#45)."""
    make_session = async_sessionmaker(test_engine, expire_on_commit=False)
    async with make_session() as setup:
        item = InfoItem(name="race bind")
        b, c = (
            InfoSource(url=f"https://example.com/race-bind-{n}", source_specs=[_spec()])
            for n in "bc"
        )
        setup.add_all([item, b, c])
        await setup.commit()
        committed_rows += [(InfoSource, b.info_source_id), (InfoSource, c.info_source_id)]
        committed_rows.append((InfoItem, item.info_item_id))

    async with make_session() as swapper, make_session() as binder:
        await lock_info_item(swapper, item.info_item_id)
        swapper.add(InfoItemSource(info_item_id=item.info_item_id, info_source_id=b.info_source_id))
        await swapper.flush()

        task = asyncio.create_task(
            bind_info_source(
                binder, info_item_id=item.info_item_id, info_source_id=c.info_source_id
            )
        )
        done, _ = await asyncio.wait({task}, timeout=1.0)
        assert not done, "bind proceeded while a swap held the InfoItem row"

        await swapper.commit()
        with pytest.raises(ActiveBindingAlreadyExistsError):
            await asyncio.wait_for(task, timeout=10.0)
        await binder.rollback()
