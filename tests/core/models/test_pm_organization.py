"""PmOrganization: the local snapshot of a linked Power Map org (archiver#304)."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from src.core.models import InfoItem, PmOrganization

ORG_ID = "01JPM00000000000000000000A"


def _org(**overrides) -> PmOrganization:
    values = {
        "pm_org_id": ORG_ID,
        "name": "Washington State Liquor and Cannabis Board",
        "acronym": "WSLCB",
        "active": True,
        "pm_updated_at": datetime(2026, 9, 30, tzinfo=UTC),
        "checked_at": datetime(2026, 10, 6, tzinfo=UTC),
    }
    values.update(overrides)
    return PmOrganization(**values)


@pytest.mark.asyncio
async def test_round_trip_with_bookkeeping_defaults(session):
    session.add(_org())
    await session.flush()
    session.expunge_all()

    org = await session.get(PmOrganization, ORG_ID)
    assert org is not None
    assert org.name == "Washington State Liquor and Cannabis Board"
    assert org.acronym == "WSLCB"
    assert org.active is True
    for column in (
        "archived_at",
        "succeeded_by",
        "merged_into",
        "renamed_from",
        "renamed_at",
        "etag",
        "missing_since",
    ):
        assert getattr(org, column) is None, column


@pytest.mark.asyncio
async def test_an_item_links_to_a_snapshot(session):
    session.add(_org())
    await session.flush()  # no relationship() to order the inserts
    item = InfoItem(name="linked", pm_org_id=ORG_ID)
    session.add(item)
    await session.flush()
    await session.refresh(item)
    assert item.pm_org_id == ORG_ID


@pytest.mark.asyncio
async def test_pm_org_id_defaults_to_unlinked(session):
    item = InfoItem(name="unlinked")
    session.add(item)
    await session.flush()
    await session.refresh(item)
    assert item.pm_org_id is None


@pytest.mark.asyncio
async def test_an_item_cannot_link_an_org_with_no_snapshot(session):
    session.add(InfoItem(name="dangling", pm_org_id=ORG_ID))
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_a_linked_snapshot_cannot_be_deleted(session):
    org = _org()
    session.add(org)
    await session.flush()
    session.add(InfoItem(name="linked", pm_org_id=ORG_ID))
    await session.flush()
    await session.delete(org)
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_info_items_pm_org_id_is_indexed(session):
    """The follower re-points a merge's items and the type-ahead seeds from linked orgs."""
    rows = await session.execute(
        text(
            "SELECT indexname FROM pg_indexes "
            "WHERE schemaname = 'information' AND tablename = 'info_items'"
        )
    )
    assert "ix_info_items_pm_org_id" in {r[0] for r in rows}
