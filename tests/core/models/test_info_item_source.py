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
        role=None,
    )
    session.add(binding)
    await session.commit()
    await session.refresh(binding)
    assert binding.deactivated_at is None
    assert binding.role is None


@pytest.mark.asyncio
async def test_one_active_root_per_item(session, item, make_source):
    """Two active NULL-role bindings on the same item violate the unique index."""
    s1 = await make_source("https://example.com/a")
    s2 = await make_source("https://example.com/b")
    session.add_all(
        [
            InfoItemSource(
                info_item_id=item.info_item_id,
                info_source_id=s1.info_source_id,
                role=None,
            ),
            InfoItemSource(
                info_item_id=item.info_item_id,
                info_source_id=s2.info_source_id,
                role=None,
            ),
        ]
    )
    with pytest.raises(IntegrityError):
        await session.commit()


@pytest.mark.asyncio
async def test_deactivated_root_allows_new_root(session, item, make_source):
    s1 = await make_source("https://example.com/a")
    s2 = await make_source("https://example.com/b")
    old = InfoItemSource(
        info_item_id=item.info_item_id,
        info_source_id=s1.info_source_id,
        role=None,
        deactivated_at=datetime.now(UTC),
    )
    session.add(old)
    await session.commit()
    new = InfoItemSource(
        info_item_id=item.info_item_id,
        info_source_id=s2.info_source_id,
        role=None,
    )
    session.add(new)
    await session.commit()  # should not raise
    await session.refresh(new)
    assert new.deactivated_at is None


@pytest.mark.asyncio
async def test_role_check_constraint_rejects_bogus_value(session, item, make_source):
    """CHECK constraint blocks any role outside {NULL, cross_check}."""
    src = await make_source("https://example.com/x")
    session.add(
        InfoItemSource(
            info_item_id=item.info_item_id,
            info_source_id=src.info_source_id,
            role="primary",  # no longer valid
        )
    )
    with pytest.raises(IntegrityError):
        await session.commit()


@pytest.mark.asyncio
async def test_cross_check_role_accepted(session, item, make_source):
    """cross_check is allowed at the schema level.

    Shape consistency (role ↔ fragment InfoSource) is enforced in the app
    layer, not the DB — see tests/core/tools/test_bind_info_source.py.
    """
    src = await make_source("https://example.com/a")
    session.add(
        InfoItemSource(
            info_item_id=item.info_item_id,
            info_source_id=src.info_source_id,
            role="cross_check",
        )
    )
    await session.commit()  # should persist


@pytest.mark.asyncio
async def test_sub_aspect_role_rejected(session, item, make_source):
    """sub_aspect is no longer a valid role — CHECK constraint must reject it."""
    src = await make_source("https://example.com/b")
    session.add(
        InfoItemSource(
            info_item_id=item.info_item_id,
            info_source_id=src.info_source_id,
            role="sub_aspect",
        )
    )
    with pytest.raises(IntegrityError):
        await session.commit()
