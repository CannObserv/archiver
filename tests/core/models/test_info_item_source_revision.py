"""InfoItemSourceRevision binding tests."""

from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError

from src.core.models import (
    InfoItem,
    InfoItemSourceRevision,
    InfoSource,
    SourceRevision,
)


@pytest.fixture
async def item(session):
    i = InfoItem(name="t")
    session.add(i)
    await session.flush()
    return i


@pytest.fixture
async def revision(session):
    src = InfoSource(
        source_spec={
            "schema_version": 1,
            "target": {"url": "https://example.com/p"},
            "extraction": {"algorithm": "full_page"},
            "fingerprint": {},
        },
        schema_version=1,
    )
    session.add(src)
    await session.flush()
    rev = SourceRevision(
        info_source_id=src.info_source_id,
        content_fingerprint="sha256:" + "a" * 64,
        captured_at=datetime.now(UTC),
    )
    session.add(rev)
    await session.flush()
    return rev


@pytest.mark.asyncio
async def test_round_trip(session, item, revision):
    bound_at = datetime.now(UTC)
    binding = InfoItemSourceRevision(
        info_item_id=item.info_item_id,
        source_revision_id=revision.source_revision_id,
        bound_at=bound_at,
    )
    session.add(binding)
    await session.commit()
    await session.refresh(binding)
    assert binding.info_item_id == item.info_item_id
    assert binding.source_revision_id == revision.source_revision_id


@pytest.mark.asyncio
async def test_duplicate_binding_rejected(session, item, revision):
    """Composite PK prevents the same (item, revision) pair appearing twice."""
    bound_at = datetime.now(UTC)
    a = InfoItemSourceRevision(
        info_item_id=item.info_item_id,
        source_revision_id=revision.source_revision_id,
        bound_at=bound_at,
    )
    b = InfoItemSourceRevision(
        info_item_id=item.info_item_id,
        source_revision_id=revision.source_revision_id,
        bound_at=bound_at,
    )
    session.add_all([a, b])
    with pytest.raises(IntegrityError):
        await session.commit()
