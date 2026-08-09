"""SourceRevision model tests."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from src.core.models import InfoSource, SourceRevision


def _spec_doc() -> dict:
    return {
        "schema_version": 1,
        "extraction": {"algorithm": "full_page"},
        "fingerprint": {},
    }


@pytest.fixture
async def root_source(session):
    src = InfoSource(url="https://example.com/p", source_specs=[_spec_doc()])
    session.add(src)
    await session.flush()
    return src


@pytest.mark.asyncio
async def test_source_revision_round_trip(session, root_source):
    rev = SourceRevision(
        info_source_id=root_source.info_source_id,
        content_fingerprint="sha256:" + "a" * 64,
        captured_at=datetime.now(UTC),
        content_size_bytes=1234,
        content_media_type="text/html",
    )
    session.add(rev)
    await session.commit()
    await session.refresh(rev)
    assert str(rev.source_revision_id)
    assert rev.content_cache_uri is None
    assert rev.content_cache_expires_at is None


@pytest.mark.asyncio
async def test_dedup_via_unique_constraint(session, root_source):
    fp = "sha256:" + "b" * 64
    a = SourceRevision(
        info_source_id=root_source.info_source_id,
        content_fingerprint=fp,
        captured_at=datetime.now(UTC),
    )
    b = SourceRevision(
        info_source_id=root_source.info_source_id,
        content_fingerprint=fp,
        captured_at=datetime.now(UTC) + timedelta(seconds=1),
    )
    session.add_all([a, b])
    with pytest.raises(IntegrityError):
        await session.commit()


@pytest.mark.asyncio
async def test_cache_fields_optional(session, root_source):
    rev = SourceRevision(
        info_source_id=root_source.info_source_id,
        content_fingerprint="sha256:" + "c" * 64,
        captured_at=datetime.now(UTC),
        content_cache_uri="file:///var/cache/archiver/01HZZ.bin",
        content_cache_expires_at=datetime.now(UTC) + timedelta(seconds=600),
    )
    session.add(rev)
    await session.commit()
    await session.refresh(rev)
    assert rev.content_cache_uri.startswith("file://")


@pytest.mark.asyncio
async def test_observation_provenance_columns_round_trip(session, root_source):
    """``source_media_type`` / ``spec_fingerprint`` / ``command_id`` (archiver#139).

    All three arrive on ``SourceRevisionObservedEvent`` and had nowhere to land
    before this migration. Nullable because the HTTP authoring/backfill path
    supplies none of them, and because ``spec_fingerprint`` / ``command_id`` are
    optional on the wire.
    """
    rev = SourceRevision(
        info_source_id=root_source.info_source_id,
        content_fingerprint="sha256:" + "f" * 64,
        captured_at=datetime.now(UTC),
        source_media_type="text/html",
        spec_fingerprint="sha256:" + "e" * 64,
        command_id="cmd-provenance",
    )
    session.add(rev)
    await session.flush()
    await session.refresh(rev)

    assert rev.source_media_type == "text/html"
    assert rev.spec_fingerprint == "sha256:" + "e" * 64
    assert rev.command_id == "cmd-provenance"


@pytest.mark.asyncio
async def test_observation_provenance_columns_default_to_null(session, root_source):
    """The HTTP path supplies none of the three; the row is still valid."""
    rev = SourceRevision(
        info_source_id=root_source.info_source_id,
        content_fingerprint="sha256:" + "9" * 64,
        captured_at=datetime.now(UTC),
    )
    session.add(rev)
    await session.flush()
    await session.refresh(rev)

    assert rev.source_media_type is None
    assert rev.spec_fingerprint is None
    assert rev.command_id is None
