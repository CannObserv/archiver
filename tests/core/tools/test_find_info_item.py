"""Unit tests for find_info_item — substring search helper."""

from datetime import UTC, datetime

import pytest
from ulid import ULID

from src.core.models import InfoItem
from src.core.tools.find_info_item import find_info_item


@pytest.mark.asyncio
async def test_find_info_item_empty_query_raises(session):
    with pytest.raises(ValueError):
        await find_info_item(session, "")


@pytest.mark.asyncio
async def test_find_info_item_orders_newest_first(session):
    # Explicit stamps: two Python-side defaults in a row can tie (archiver#149).
    session.add(InfoItem(name="alpha-1", created_at=datetime(2026, 1, 1, tzinfo=UTC)))
    session.add(InfoItem(name="alpha-2", created_at=datetime(2026, 1, 2, tzinfo=UTC)))
    await session.flush()

    results = await find_info_item(session, "alpha")
    assert [r.name for r in results] == ["alpha-2", "alpha-1"]


@pytest.mark.asyncio
async def test_find_info_item_breaks_created_at_ties_by_id_descending(session):
    """Equal ``created_at`` falls to ``info_item_id DESC`` (archiver#149).

    The tie is forced, not hoped for: rows go in ascending-id order, so heap order
    (what an untiebroken sort returns) is the reverse of the rule. ULIDs are not
    reliably monotonic within a millisecond, so the rule is id order, not insertion order.
    """
    stamp = datetime(2026, 1, 1, tzinfo=UTC)
    ids = sorted(ULID() for _ in range(5))
    for i in ids:
        session.add(InfoItem(info_item_id=i, name=f"gamma-{i}", created_at=stamp))
        await session.flush()

    results = await find_info_item(session, "gamma")
    assert [r.info_item_id for r in results] == sorted(ids, reverse=True)


@pytest.mark.asyncio
async def test_find_info_item_respects_limit(session):
    for i in range(5):
        session.add(InfoItem(name=f"beta-{i}"))
    await session.flush()

    results = await find_info_item(session, "beta", limit=3)
    assert len(results) == 3
