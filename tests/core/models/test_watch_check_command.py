"""WatchCheckCommand column contracts (archiver#370 D2)."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, select
from ulid import ULID

from src.core.models import AppUser, InfoItem, WatchCheckCommand

T0 = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)


async def _item(session) -> InfoItem:
    item = InfoItem(name="check-now probe")
    session.add(item)
    await session.flush()
    return item


@pytest.mark.asyncio
async def test_a_command_records_who_asked_and_when(session):
    item = await _item(session)
    user = AppUser(external_id="ext-370", email="op@example.com")
    session.add(user)
    await session.flush()
    command_id = str(ULID())
    session.add(
        WatchCheckCommand(
            command_id=command_id,
            info_item_id=item.info_item_id,
            requested_at=T0,
            requested_by=user.id,
        )
    )
    await session.commit()

    row = await session.get(WatchCheckCommand, command_id)
    assert row.requested_at == T0
    assert row.requested_by == user.id
    assert row.created_at is not None
    assert row.rejected_reason is None
    assert row.rejected_at is None


@pytest.mark.asyncio
async def test_deleting_the_item_deletes_its_commands(session):
    item = await _item(session)
    command_id = str(ULID())
    session.add(
        WatchCheckCommand(command_id=command_id, info_item_id=item.info_item_id, requested_at=T0)
    )
    await session.commit()

    await session.execute(delete(InfoItem).where(InfoItem.info_item_id == item.info_item_id))
    await session.commit()

    left = await session.execute(
        select(WatchCheckCommand).where(WatchCheckCommand.command_id == command_id)
    )
    assert left.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_deleting_the_operator_keeps_the_command(session):
    """History outlives the operator: ``requested_by`` is SET NULL."""
    item = await _item(session)
    user = AppUser(external_id="ext-370-gone", email="gone@example.com")
    session.add(user)
    await session.flush()
    command_id = str(ULID())
    session.add(
        WatchCheckCommand(
            command_id=command_id,
            info_item_id=item.info_item_id,
            requested_at=T0,
            requested_by=user.id,
        )
    )
    await session.commit()

    await session.execute(delete(AppUser).where(AppUser.id == user.id))
    await session.commit()
    session.expire_all()

    row = await session.get(WatchCheckCommand, command_id)
    assert row is not None
    assert row.requested_by is None
