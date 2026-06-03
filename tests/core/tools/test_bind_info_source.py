"""Tests for the bind_info_source core tool."""

from datetime import UTC, datetime

import pytest
from ulid import ULID

from src.core.models import InfoItem, InfoItemSource, InfoSource
from src.core.tools.bind_info_source import (
    ActiveBindingAlreadyExistsError,
    InfoItemNotFoundError,
    InfoSourceNotFoundError,
    bind_info_source,
)


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
