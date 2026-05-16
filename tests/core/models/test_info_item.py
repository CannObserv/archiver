"""InfoItem ORM round-trip tests."""

import pytest
from sqlalchemy import select, text

from src.core.models import InfoItem


@pytest.mark.asyncio
async def test_info_item_round_trip(session):
    item = InfoItem(name="Colorado active licenses", description="Roster page", owner="greg")
    session.add(item)
    await session.commit()

    result = await session.execute(
        select(InfoItem).where(InfoItem.info_item_id == item.info_item_id)
    )
    fetched = result.scalar_one()
    assert fetched.name == "Colorado active licenses"
    assert fetched.description == "Roster page"
    assert fetched.owner == "greg"
    assert str(fetched.info_item_id)  # ULID generated


@pytest.mark.asyncio
async def test_info_item_has_rep_fields_default_empty(session):
    item = InfoItem(name="t")
    session.add(item)
    await session.commit()
    await session.refresh(item)
    assert item.rep_fields == {}


@pytest.mark.asyncio
async def test_info_item_rep_fields_round_trips_nested_json(session):
    item = InfoItem(name="t", rep_fields={"org": {"acronym": "wslcb"}})
    session.add(item)
    await session.commit()
    await session.refresh(item)
    assert item.rep_fields == {"org": {"acronym": "wslcb"}}


@pytest.mark.asyncio
async def test_info_items_has_pg_trgm_indexes(session):
    """find_info_item ILIKE search relies on GIN trigram indexes to avoid
    tablescans as the catalog grows (archiver#23)."""
    result = await session.execute(
        text(
            "SELECT indexname FROM pg_indexes "
            "WHERE schemaname = 'information' AND tablename = 'info_items'"
        )
    )
    index_names = {row[0] for row in result.all()}
    assert "ix_info_items_name_trgm" in index_names
    assert "ix_info_items_description_trgm" in index_names
