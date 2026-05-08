"""InfoItemSource binding tests."""

from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError

from src.core.models import InfoItem, InfoItemSource, InfoSource


@pytest.fixture
async def item(session):
    i = InfoItem(name="t")
    session.add(i)
    await session.flush()
    return i


@pytest.fixture
async def make_source(session):
    async def _make(url: str) -> InfoSource:
        src = InfoSource(
            source_spec={
                "schema_version": 1,
                "target": {"url": url},
                "extraction": {"algorithm": "full_page"},
                "fingerprint": {},
            },
            schema_version=1,
        )
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
        role="primary",
    )
    session.add(binding)
    await session.commit()
    await session.refresh(binding)
    assert binding.deactivated_at is None
    assert binding.role == "primary"


@pytest.mark.asyncio
async def test_one_active_primary_per_item(session, item, make_source):
    s1 = await make_source("https://example.com/a")
    s2 = await make_source("https://example.com/b")
    session.add_all([
        InfoItemSource(
            info_item_id=item.info_item_id,
            info_source_id=s1.info_source_id,
            role="primary",
        ),
        InfoItemSource(
            info_item_id=item.info_item_id,
            info_source_id=s2.info_source_id,
            role="primary",
        ),
    ])
    with pytest.raises(IntegrityError):
        await session.commit()


@pytest.mark.asyncio
async def test_deactivated_primary_allows_new_primary(session, item, make_source):
    s1 = await make_source("https://example.com/a")
    s2 = await make_source("https://example.com/b")
    old = InfoItemSource(
        info_item_id=item.info_item_id,
        info_source_id=s1.info_source_id,
        role="primary",
        deactivated_at=datetime.now(UTC),
    )
    session.add(old)
    await session.commit()
    new = InfoItemSource(
        info_item_id=item.info_item_id,
        info_source_id=s2.info_source_id,
        role="primary",
    )
    session.add(new)
    await session.commit()  # should not raise
    await session.refresh(new)
    assert new.deactivated_at is None


@pytest.mark.asyncio
async def test_secondary_role_unconstrained(session, item, make_source):
    """Multiple active 'secondary' bindings on the same item are allowed.

    The partial unique index only constrains role='primary'.
    """
    s1 = await make_source("https://example.com/a")
    s2 = await make_source("https://example.com/b")
    session.add_all([
        InfoItemSource(
            info_item_id=item.info_item_id,
            info_source_id=s1.info_source_id,
            role="secondary",
        ),
        InfoItemSource(
            info_item_id=item.info_item_id,
            info_source_id=s2.info_source_id,
            role="secondary",
        ),
    ])
    await session.commit()  # should not raise
