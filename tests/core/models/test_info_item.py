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
    tablescans as the catalog grows. Assert each expected index is present
    *and* is a GIN index using gin_trgm_ops so a future btree rename can't
    silently pass this tripwire."""
    result = await session.execute(
        text(
            "SELECT indexname, indexdef FROM pg_indexes "
            "WHERE schemaname = 'information' AND tablename = 'info_items'"
        )
    )
    indexes = {row[0]: row[1] for row in result.all()}
    for name in ("ix_info_items_name_trgm", "ix_info_items_description_trgm"):
        assert name in indexes, f"missing index {name}"
        definition = indexes[name].lower()
        assert "using gin" in definition, f"{name} is not a GIN index: {indexes[name]}"
        assert "gin_trgm_ops" in definition, f"{name} missing gin_trgm_ops: {indexes[name]}"


@pytest.mark.asyncio
async def test_info_item_watch_spec_defaults_to_active_without_a_cadence(session):
    """The default policy is 'scheduled', with the interval left to the consumer.

    A resolved interval here would fabricate a cadence for every item that has
    none and override Watcher's per-domain default.
    """
    item = InfoItem(name="t")
    session.add(item)
    await session.commit()
    await session.refresh(item)
    assert item.watch_spec == {"schema_version": 1, "active": True}


@pytest.mark.asyncio
async def test_info_item_watch_spec_round_trips_an_explicit_policy(session):
    item = InfoItem(name="t", watch_spec={"schema_version": 1, "active": False, "interval": "6h"})
    session.add(item)
    await session.commit()
    await session.refresh(item)
    assert item.watch_spec == {"schema_version": 1, "active": False, "interval": "6h"}


@pytest.mark.asyncio
async def test_info_item_watch_spec_server_default_applies_to_raw_inserts(session):
    """Rows written outside the ORM — including the ones the migration backfills
    — get the same policy, so nothing reads NULL."""
    await session.execute(
        text(
            "INSERT INTO information.info_items (info_item_id, name) "
            "VALUES ('01J0000000000000000000000X', 'raw')"
        )
    )
    row = await session.execute(
        text(
            "SELECT watch_spec FROM information.info_items "
            "WHERE info_item_id = '01J0000000000000000000000X'"
        )
    )
    assert row.scalar_one() == {"schema_version": 1, "active": True}
