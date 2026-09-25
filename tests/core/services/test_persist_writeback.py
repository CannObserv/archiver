"""Closing a persist command from ``content.artifacts`` (archiver#276, cannobserv#493).

What differs from replication's writeback:

- **The outcome belongs to the digest, not the command.** Neither fact carries a
  revision or source id; the stored object is shared by every revision whose raw
  bytes hash to it. A success stamps ``persisted_at`` on all of them.
- **``persisted_at`` is a minimum, not a first write.** ``occurred_at`` is the
  publish time, an upper bound on the write, and a redelivery or a later command
  re-emits with a later stamp. The earliest fact for the digest wins, whatever
  order the facts arrive in.
- **Branch on ``terminal`` first; ``reason`` is opaque.**
"""

from datetime import UTC, datetime, timedelta

import pytest

from src.core.models import InfoSource, PersistCommand, SourceRevision
from src.core.services.persist_writeback import (
    REASON_DIGEST_MISMATCH,
    STATE_FAILED,
    STATE_PERSISTED,
    STATE_REQUESTED,
    apply_persist_failed,
    apply_persisted,
)
from src.core.services.replication_writeback import UnknownCommandError

DIGEST = "d" * 64
OTHER_DIGEST = "9" * 64
OCCURRED_AT = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)


async def _revision(session, *, url: str, digest: str | None, fp: str = "a") -> SourceRevision:
    source = InfoSource(url=url, source_specs=[])
    session.add(source)
    await session.flush()
    revision = SourceRevision(
        info_source_id=source.info_source_id,
        content_fingerprint="sha256:" + fp * 64,
        captured_at=datetime.now(UTC),
        blob_fingerprint=digest,
    )
    session.add(revision)
    await session.flush()
    return revision


@pytest.fixture
async def revision(session) -> SourceRevision:
    return await _revision(session, url="https://example.com/persist-1", digest=DIGEST)


async def _command(session, revision, *, command_id: str = "pcmd-1") -> PersistCommand:
    command = PersistCommand(
        command_id=command_id,
        source_revision_id=revision.source_revision_id,
        content_fingerprint=revision.blob_fingerprint,
        blob_uri=f"gs://co-gcs-blobs/blobs/{revision.blob_fingerprint}.bin",
        media_type="text/html",
        state=STATE_REQUESTED,
    )
    session.add(command)
    await session.flush()
    return command


# --- blob_persisted ---


@pytest.mark.asyncio
async def test_success_closes_the_command_and_stamps_the_revision(session, revision):
    command = await _command(session, revision)

    await apply_persisted(
        session,
        command_id="pcmd-1",
        content_fingerprint=DIGEST,
        size_bytes=1234,
        occurred_at=OCCURRED_AT,
    )

    await session.refresh(revision)
    assert command.state == STATE_PERSISTED
    assert command.terminal is True
    assert command.size_bytes == 1234
    assert command.closed_at is not None
    assert command.last_fact_at == OCCURRED_AT
    assert revision.persisted_at == OCCURRED_AT


@pytest.mark.asyncio
async def test_success_stamps_every_revision_sharing_the_digest(session, revision):
    """The object belongs to the digest: another source's revision with the same
    bytes is persisted too, and a revision with other bytes is not."""
    sibling = await _revision(
        session, url="https://example.com/persist-sibling", digest=DIGEST, fp="b"
    )
    stranger = await _revision(
        session, url="https://example.com/persist-other", digest=OTHER_DIGEST, fp="c"
    )
    unknown = await _revision(session, url="https://example.com/persist-none", digest=None, fp="e")
    await _command(session, revision)

    await apply_persisted(
        session,
        command_id="pcmd-1",
        content_fingerprint=DIGEST,
        size_bytes=1,
        occurred_at=OCCURRED_AT,
    )
    await session.refresh(sibling)
    await session.refresh(stranger)
    await session.refresh(unknown)

    assert sibling.persisted_at == OCCURRED_AT
    assert stranger.persisted_at is None
    assert unknown.persisted_at is None


@pytest.mark.asyncio
async def test_a_later_success_does_not_move_persisted_at_forward(session, revision):
    """A redelivery or a second command re-emits with a later stamp; the earliest stands."""
    await _command(session, revision, command_id="pcmd-1")
    await _command(session, revision, command_id="pcmd-2")

    await apply_persisted(
        session,
        command_id="pcmd-1",
        content_fingerprint=DIGEST,
        size_bytes=1,
        occurred_at=OCCURRED_AT,
    )
    await apply_persisted(
        session,
        command_id="pcmd-2",
        content_fingerprint=DIGEST,
        size_bytes=1,
        occurred_at=OCCURRED_AT + timedelta(hours=1),
    )
    await session.refresh(revision)

    assert revision.persisted_at == OCCURRED_AT


@pytest.mark.asyncio
async def test_an_earlier_success_arriving_late_moves_persisted_at_back(session, revision):
    """Out-of-order delivery: the minimum over every fact, not the first to arrive."""
    await _command(session, revision, command_id="pcmd-1")
    await _command(session, revision, command_id="pcmd-2")

    await apply_persisted(
        session,
        command_id="pcmd-2",
        content_fingerprint=DIGEST,
        size_bytes=1,
        occurred_at=OCCURRED_AT + timedelta(hours=1),
    )
    await apply_persisted(
        session,
        command_id="pcmd-1",
        content_fingerprint=DIGEST,
        size_bytes=1,
        occurred_at=OCCURRED_AT,
    )
    await session.refresh(revision)

    assert revision.persisted_at == OCCURRED_AT


@pytest.mark.asyncio
async def test_repeated_success_is_idempotent(session, revision):
    command = await _command(session, revision)
    kwargs = dict(
        command_id="pcmd-1", content_fingerprint=DIGEST, size_bytes=5, occurred_at=OCCURRED_AT
    )

    await apply_persisted(session, **kwargs)
    first_closed_at = command.closed_at
    await apply_persisted(session, **kwargs)

    await session.refresh(revision)
    assert command.state == STATE_PERSISTED
    assert command.closed_at == first_closed_at
    assert revision.persisted_at == OCCURRED_AT


@pytest.mark.asyncio
async def test_success_for_a_different_digest_stamps_nothing(session, revision):
    """The success Emit validates its digest, so a mismatch is a producer bug. Stamping
    the command's digest would send later publications to an object that is not there."""
    command = await _command(session, revision)

    await apply_persisted(
        session,
        command_id="pcmd-1",
        content_fingerprint=OTHER_DIGEST,
        size_bytes=1,
        occurred_at=OCCURRED_AT,
    )

    await session.refresh(revision)
    assert revision.persisted_at is None
    assert command.state == STATE_FAILED
    assert command.reason == REASON_DIGEST_MISMATCH
    assert command.terminal is True


@pytest.mark.asyncio
async def test_unknown_command_is_reported_not_written(session, revision):
    with pytest.raises(UnknownCommandError):
        await apply_persisted(
            session,
            command_id="never-issued",
            content_fingerprint=DIGEST,
            size_bytes=1,
            occurred_at=OCCURRED_AT,
        )
    await session.refresh(revision)
    assert revision.persisted_at is None


# --- persist_failed ---


@pytest.mark.asyncio
async def test_terminal_failure_closes_the_command_with_the_producers_reason(session, revision):
    command = await _command(session, revision)

    await apply_persist_failed(
        session,
        command_id="pcmd-1",
        reason="blob_expired",
        terminal=True,
        detail="gone",
        occurred_at=OCCURRED_AT,
    )

    await session.refresh(revision)
    assert command.state == STATE_FAILED
    assert command.reason == "blob_expired"
    assert command.detail == "gone"
    assert command.terminal is True
    assert command.closed_at is not None
    assert revision.persisted_at is None


@pytest.mark.asyncio
async def test_non_terminal_failure_leaves_the_command_open(session, revision):
    command = await _command(session, revision)

    await apply_persist_failed(
        session,
        command_id="pcmd-1",
        reason="some_new_token",
        terminal=False,
        detail=None,
        occurred_at=OCCURRED_AT,
    )

    assert command.state == STATE_REQUESTED
    assert command.reason == "some_new_token"
    assert command.terminal is False
    assert command.closed_at is None


@pytest.mark.asyncio
async def test_failure_after_success_does_not_unmake_the_persist(session, revision):
    command = await _command(session, revision)
    await apply_persisted(
        session,
        command_id="pcmd-1",
        content_fingerprint=DIGEST,
        size_bytes=1,
        occurred_at=OCCURRED_AT,
    )

    await apply_persist_failed(
        session,
        command_id="pcmd-1",
        reason="invalid_source",
        terminal=True,
        detail=None,
        occurred_at=OCCURRED_AT + timedelta(minutes=5),
    )

    await session.refresh(revision)
    assert command.state == STATE_PERSISTED
    assert revision.persisted_at == OCCURRED_AT


@pytest.mark.asyncio
async def test_stale_failure_is_ignored(session, revision):
    """A redelivered older retry notice must not reopen diagnostics a newer one closed."""
    command = await _command(session, revision)
    await apply_persist_failed(
        session,
        command_id="pcmd-1",
        reason="blob_expired",
        terminal=True,
        detail=None,
        occurred_at=OCCURRED_AT,
    )

    await apply_persist_failed(
        session,
        command_id="pcmd-1",
        reason="transient",
        terminal=False,
        detail=None,
        occurred_at=OCCURRED_AT - timedelta(minutes=1),
    )

    assert command.state == STATE_FAILED
    assert command.reason == "blob_expired"


@pytest.mark.asyncio
async def test_failure_for_unknown_command_raises(session):
    with pytest.raises(UnknownCommandError):
        await apply_persist_failed(
            session,
            command_id="never-issued",
            reason="blob_expired",
            terminal=True,
            detail=None,
            occurred_at=OCCURRED_AT,
        )


@pytest.mark.asyncio
async def test_success_wins_over_a_newer_failure_whatever_the_arrival_order(session, revision):
    """The object exists once any success says so. A failure stamped later cannot
    unmake it, so an older success arriving late still closes the command persisted."""
    command = await _command(session, revision)
    await apply_persist_failed(
        session,
        command_id="pcmd-1",
        reason="blob_expired",
        terminal=True,
        detail=None,
        occurred_at=OCCURRED_AT + timedelta(minutes=5),
    )

    await apply_persisted(
        session,
        command_id="pcmd-1",
        content_fingerprint=DIGEST,
        size_bytes=9,
        occurred_at=OCCURRED_AT,
    )
    await session.refresh(revision)

    assert command.state == STATE_PERSISTED
    assert command.reason is None
    assert command.size_bytes == 9
    assert command.last_fact_at == OCCURRED_AT + timedelta(minutes=5)
    assert revision.persisted_at == OCCURRED_AT
