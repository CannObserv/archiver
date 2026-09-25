"""PersistCommand column contracts (archiver#276)."""

from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError
from ulid import ULID

from src.core.models import InfoSource, PersistCommand, SourceRevision

DIGEST = "e" * 64


async def _revision(session) -> SourceRevision:
    source = InfoSource(url="https://example.com/persist-state", source_specs=[])
    session.add(source)
    await session.flush()
    revision = SourceRevision(
        info_source_id=source.info_source_id,
        content_fingerprint="sha256:" + "f" * 64,
        captured_at=datetime.now(UTC),
        blob_fingerprint=DIGEST,
    )
    session.add(revision)
    await session.flush()
    return revision


def _command(revision, state: str) -> PersistCommand:
    return PersistCommand(
        command_id=str(ULID()),
        source_revision_id=revision.source_revision_id,
        content_fingerprint=DIGEST,
        blob_uri=f"gs://co-gcs-blobs/blobs/{DIGEST}.bin",
        media_type="text/html",
        state=state,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["requested", "persisted", "failed", "abandoned"])
async def test_known_states_are_accepted(session, state):
    revision = await _revision(session)
    session.add(_command(revision, state))
    await session.flush()


@pytest.mark.asyncio
async def test_unknown_state_is_rejected_by_the_database(session):
    """The open-command index hard-codes ``state = 'requested'``, as replication's does:
    a mistyped state would otherwise stop matching and read as an empty queue."""
    revision = await _revision(session)
    session.add(_command(revision, "complete"))
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_revision_persist_columns_default_to_null(session):
    """Rows written before Watcher sends the digest (watcher#329) carry neither."""
    source = InfoSource(url="https://example.com/persist-null", source_specs=[])
    session.add(source)
    await session.flush()
    revision = SourceRevision(
        info_source_id=source.info_source_id,
        content_fingerprint="sha256:" + "a" * 64,
        captured_at=datetime.now(UTC),
    )
    session.add(revision)
    await session.flush()
    assert revision.blob_fingerprint is None
    assert revision.persisted_at is None
