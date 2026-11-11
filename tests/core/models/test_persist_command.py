"""PersistCommand column contracts (archiver#276)."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from ulid import ULID

from src.core.models import CaptureCommand, InfoSource, PersistCommand, SourceRevision

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


# --- the occasion: a revision or a capture, exactly one (archiver#380 slice B) ---


async def _capture(session) -> CaptureCommand:
    source = InfoSource(url="https://example.com/persist-capture", source_specs=[])
    session.add(source)
    await session.flush()
    capture = CaptureCommand(
        command_id=str(ULID()),
        info_source_id=source.info_source_id,
        url=source.url,
        viewport_width=1280,
        viewport_height=800,
        full_page=True,
        state="stored",
        content_fingerprint=DIGEST,
    )
    session.add(capture)
    await session.flush()
    return capture


def _capture_persist(capture, **overrides) -> PersistCommand:
    values = dict(
        command_id=str(ULID()),
        capture_command_id=capture.command_id,
        content_fingerprint=DIGEST,
        blob_uri=f"gs://co-gcs-blobs/blobs/{DIGEST}.bin",
        media_type="image/png",
        state="requested",
    )
    values.update(overrides)
    return PersistCommand(**values)


@pytest.mark.asyncio
async def test_a_capture_can_occasion_a_persist(session):
    capture = await _capture(session)
    command = _capture_persist(capture)
    session.add(command)
    await session.flush()
    assert command.source_revision_id is None
    assert command.capture_command_id == capture.command_id


@pytest.mark.asyncio
async def test_a_persist_with_no_occasion_is_rejected(session):
    session.add(
        PersistCommand(
            command_id=str(ULID()),
            content_fingerprint=DIGEST,
            blob_uri="gs://x",
            media_type="image/png",
            state="requested",
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_a_persist_with_both_occasions_is_rejected(session):
    revision = await _revision(session)
    capture = await _capture(session)
    session.add(_capture_persist(capture, source_revision_id=revision.source_revision_id))
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_deleting_the_capture_deletes_its_persists(session):
    capture = await _capture(session)
    command = _capture_persist(capture)
    session.add(command)
    await session.commit()
    command_id = command.command_id

    await session.execute(
        delete(CaptureCommand).where(CaptureCommand.command_id == capture.command_id)
    )
    await session.commit()

    left = await session.execute(
        select(PersistCommand).where(PersistCommand.command_id == command_id)
    )
    assert left.scalar_one_or_none() is None
