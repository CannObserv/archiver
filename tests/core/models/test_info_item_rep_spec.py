"""InfoItemRepSpec assignment tests."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.core.models import InfoItem, InfoItemRepSpec, RepSpec


@pytest.fixture
async def item(session):
    i = InfoItem(name="t")
    session.add(i)
    await session.flush()
    return i


@pytest.fixture
async def rep_spec(session):
    spec = RepSpec(provider="gcs", name="default", schema_version=1, document={"provider": "gcs"})
    session.add(spec)
    await session.flush()
    return spec


@pytest.mark.asyncio
async def test_round_trip_active(session, item, rep_spec):
    """A new assignment is active (deactivated_at NULL); public_url initially NULL."""
    assignment = InfoItemRepSpec(
        info_item_id=item.info_item_id,
        rep_spec_id=rep_spec.rep_spec_id,
        activated_at=datetime.now(UTC),
    )
    session.add(assignment)
    await session.commit()
    await session.refresh(assignment)
    assert str(assignment.id)
    assert assignment.deactivated_at is None
    assert assignment.public_url is None


@pytest.mark.asyncio
async def test_public_url_writeback(session, item, rep_spec):
    """Replicator writeback updates public_url on the active row."""
    assignment = InfoItemRepSpec(
        info_item_id=item.info_item_id,
        rep_spec_id=rep_spec.rep_spec_id,
        activated_at=datetime.now(UTC),
    )
    session.add(assignment)
    await session.commit()

    assignment.public_url = "https://storage.googleapis.com/bucket/path"
    await session.commit()
    await session.refresh(assignment)
    assert assignment.public_url == "https://storage.googleapis.com/bucket/path"


@pytest.mark.asyncio
async def test_two_active_assignments_to_same_rep_spec_rejected(session, item, rep_spec):
    """``uq_iirs_item_spec_active`` refuses on its own, without assign_rep_spec (archiver#301).

    Both rows would render one destination, and issuance skips both as
    ``destination_collision`` on every occasion.
    """
    for _ in range(2):
        session.add(
            InfoItemRepSpec(
                info_item_id=item.info_item_id,
                rep_spec_id=rep_spec.rep_spec_id,
                activated_at=datetime.now(UTC),
            )
        )
    with pytest.raises(IntegrityError, match="uq_iirs_item_spec_active"):
        await session.flush()


@pytest.mark.asyncio
async def test_a_deactivated_assignment_may_repeat_an_active_one(session, item, rep_spec):
    """History is not a duplicate: the index covers active rows only."""
    now = datetime.now(UTC)
    session.add_all(
        [
            InfoItemRepSpec(
                info_item_id=item.info_item_id,
                rep_spec_id=rep_spec.rep_spec_id,
                activated_at=now,
                deactivated_at=now,
            ),
            InfoItemRepSpec(
                info_item_id=item.info_item_id, rep_spec_id=rep_spec.rep_spec_id, activated_at=now
            ),
        ]
    )
    await session.commit()
    result = await session.execute(
        select(InfoItemRepSpec).where(InfoItemRepSpec.info_item_id == item.info_item_id)
    )
    assert len(list(result.scalars())) == 2


@pytest.mark.asyncio
async def test_deactivated_assignment_preserves_public_url(session, item, rep_spec):
    """History: deactivated_at set, public_url retained for migration tooling."""
    assignment = InfoItemRepSpec(
        info_item_id=item.info_item_id,
        rep_spec_id=rep_spec.rep_spec_id,
        activated_at=datetime.now(UTC),
        public_url="https://example.com/archived",
    )
    session.add(assignment)
    await session.commit()

    assignment.deactivated_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(assignment)
    assert assignment.deactivated_at is not None
    assert assignment.public_url == "https://example.com/archived"
