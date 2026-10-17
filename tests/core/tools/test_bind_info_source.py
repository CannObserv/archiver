"""Tests for the bind_info_source core tool."""

import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker
from ulid import ULID

from src.core.models import InfoItem, InfoItemSource, InfoSource
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
