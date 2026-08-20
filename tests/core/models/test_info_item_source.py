"""InfoItemSource binding tests."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from src.core.models import InfoItem, InfoItemSource, InfoSource


def _spec() -> dict:
    return {
        "schema_version": 1,
        "extraction": {"algorithm": "full_page"},
        "fingerprint": {},
    }


@pytest.fixture
async def item(session):
    i = InfoItem(name="t")
    session.add(i)
    await session.flush()
    return i


@pytest.fixture
async def make_source(session):
    async def _make(url: str) -> InfoSource:
        src = InfoSource(url=url, source_specs=[_spec()])
        session.add(src)
        await session.flush()
        return src

    return _make


@pytest.mark.asyncio
async def test_round_trip(session, item, make_source):
    src = await make_source("https://example.com/p")
    binding = InfoItemSource(
        info_item_id=item.info_item_id,
        info_source_id=src.info_source_id,
    )
    session.add(binding)
    await session.commit()
    await session.refresh(binding)
    assert binding.deactivated_at is None


@pytest.mark.asyncio
async def test_one_active_per_item(session, item, make_source):
    """Two active bindings on the same item violate the unique index."""
    s1 = await make_source("https://example.com/a")
    s2 = await make_source("https://example.com/b")
    session.add_all(
        [
            InfoItemSource(info_item_id=item.info_item_id, info_source_id=s1.info_source_id),
            InfoItemSource(info_item_id=item.info_item_id, info_source_id=s2.info_source_id),
        ]
    )
    with pytest.raises(IntegrityError):
        await session.commit()


@pytest.mark.asyncio
async def test_deactivated_allows_new_active(session, item, make_source):
    s1 = await make_source("https://example.com/a")
    s2 = await make_source("https://example.com/b")
    old = InfoItemSource(
        info_item_id=item.info_item_id,
        info_source_id=s1.info_source_id,
        deactivated_at=datetime.now(UTC),
    )
    session.add(old)
    await session.commit()
    new = InfoItemSource(
        info_item_id=item.info_item_id,
        info_source_id=s2.info_source_id,
    )
    session.add(new)
    await session.commit()
    await session.refresh(new)
    assert new.deactivated_at is None


@pytest.mark.asyncio
async def test_info_item_sources_has_active_source_index(session):
    """The source→item direction needs its own index (archiver#176).

    Every earlier consumer entered this table by ``info_item_id``, which the
    composite primary key leads with. Domain detail enters by
    ``info_source_id`` instead — a column the PK index cannot serve, since
    Postgres has no skip scan — so without this index the domain screen
    sequentially scans every binding, twice per render.

    Partial on ``deactivated_at IS NULL`` because that predicate is in the
    query: a deactivated binding is succession history, never a current
    dependency.
    """
    result = await session.execute(
        text(
            "SELECT indexname, indexdef FROM pg_indexes "
            "WHERE schemaname = 'information' AND tablename = 'info_item_sources'"
        )
    )
    indexes = {row[0]: row[1] for row in result.all()}
    name = "ix_info_item_sources_active_source"
    assert name in indexes, f"missing index {name}: {sorted(indexes)}"
    definition = indexes[name].lower()
    assert "info_source_id" in definition, definition
    assert "deactivated_at is null" in definition, definition
