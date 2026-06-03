"""Tests for the deactivate_info_item_source_binding core tool."""

import pytest
from ulid import ULID

from src.core.models import InfoItem, InfoItemSource, InfoSource
from src.core.tools.deactivate_info_item_source_binding import (
    BindingNotFoundError,
    deactivate_info_item_source_binding,
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


@pytest.fixture
async def root_src(session):
    src = InfoSource(url="https://example.com/p", source_specs=[_spec()])
    session.add(src)
    await session.flush()
    return src


@pytest.fixture
async def active_binding(session, item, root_src):
    binding = InfoItemSource(
        info_item_id=item.info_item_id,
        info_source_id=root_src.info_source_id,
    )
    session.add(binding)
    await session.flush()
    return binding


@pytest.mark.asyncio
async def test_deactivate_sets_deactivated_at(session, active_binding, item, root_src):
    result = await deactivate_info_item_source_binding(
        session, info_item_id=item.info_item_id, info_source_id=root_src.info_source_id
    )
    assert result.deactivated_at is not None


@pytest.mark.asyncio
async def test_deactivate_returns_binding_row(session, active_binding, item, root_src):
    result = await deactivate_info_item_source_binding(
        session, info_item_id=item.info_item_id, info_source_id=root_src.info_source_id
    )
    assert result.info_item_id == item.info_item_id
    assert result.info_source_id == root_src.info_source_id


@pytest.mark.asyncio
async def test_deactivate_missing_binding_raises(session, item, root_src):
    with pytest.raises(BindingNotFoundError):
        await deactivate_info_item_source_binding(
            session, info_item_id=item.info_item_id, info_source_id=root_src.info_source_id
        )


@pytest.mark.asyncio
async def test_deactivate_already_deactivated_raises(session, active_binding, item, root_src):
    await deactivate_info_item_source_binding(
        session, info_item_id=item.info_item_id, info_source_id=root_src.info_source_id
    )
    # Second call — binding is now deactivated, should raise.
    with pytest.raises(BindingNotFoundError):
        await deactivate_info_item_source_binding(
            session, info_item_id=item.info_item_id, info_source_id=root_src.info_source_id
        )


@pytest.mark.asyncio
async def test_deactivate_unknown_item_raises(session, root_src):
    with pytest.raises(BindingNotFoundError):
        await deactivate_info_item_source_binding(
            session, info_item_id=ULID(), info_source_id=root_src.info_source_id
        )
