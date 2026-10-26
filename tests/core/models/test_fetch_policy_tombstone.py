"""FetchPolicyTombstone: a deleted host's last generation (archiver#366).

The row outlives the ``Domain`` it records, so every full set can keep
republishing the tombstone at the generation the delete drew.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.core.models import FetchPolicyTombstone


@pytest.mark.asyncio
async def test_tombstone_stores_host_generation_and_stamp(session):
    session.add(FetchPolicyTombstone(host="gone.example.com", generation=42))
    await session.flush()
    row = (
        await session.execute(
            select(FetchPolicyTombstone).where(FetchPolicyTombstone.host == "gone.example.com")
        )
    ).scalar_one()
    assert row.generation == 42
    assert row.revoked_at is not None


@pytest.mark.asyncio
async def test_one_tombstone_per_host(session):
    session.add(FetchPolicyTombstone(host="dup.example.com", generation=1))
    await session.flush()
    session.add(FetchPolicyTombstone(host="dup.example.com", generation=2))
    with pytest.raises(IntegrityError):
        await session.flush()
