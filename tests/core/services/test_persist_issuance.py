"""Issuing ``content.persist`` (archiver#276 PR C, replicator persist contract).

What is pinned here:

- **Off unless switched on.** ``ARCHIVER_PERSIST_ISSUANCE`` gates every issue,
  because the go-live order is Replicator enables, *then* Archiver issues
  (broker#64): a command sent before ``replicator.persist`` existed would never
  be delivered.
- **One open command per digest.** The object belongs to its digest, and a
  success stamps every revision carrying it, so a second open command for the
  same bytes buys nothing (decision 3).
- **The pair travels together (P4).** The command carries the revision's
  ``blob_fingerprint`` and ``content_cache_uri`` as recorded, never a rebuilt URI.
- **The reaper re-issues (P3).** Silence means Replicator is still retrying, so
  an open command past the horizon is abandoned and, within a cap, re-issued
  under a fresh ``command_id``. A duplicate persist is a no-op success, which
  is why re-issue is safe here and is not for replicate.
"""

from datetime import UTC, datetime, timedelta

import pytest
from co_core.pure.adapters.bus.streams import CONTENT_PERSIST
from sqlalchemy import func, select

from src.core.models import ChangesOutboxRow, InfoSource, PersistCommand, SourceRevision
from src.core.replication.permanent_store import PERMANENT_BUCKET, permanent_blob_uri
from src.core.services import persist_issuance
from src.core.services.persist_issuance import (
    MAX_REISSUES,
    REASON_NO_FACT,
    issuance_enabled,
    issue_persist,
    reap_open_persists,
)
from src.core.services.persist_writeback import (
    STATE_ABANDONED,
    STATE_FAILED,
    STATE_PERSISTED,
    STATE_REQUESTED,
)

DIGEST = "a" * 64
OTHER_DIGEST = "b" * 64
BLOB_URI = f"gs://co-gcs-blobs/blobs/{DIGEST}.bin"
HORIZON = timedelta(hours=6)


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv(persist_issuance.ISSUANCE_ENV, "1")


async def _revision(
    session,
    *,
    url: str = "https://example.com/persist-issue",
    digest: str | None = DIGEST,
    uri: str | None = BLOB_URI,
    fp: str = "a",
    **overrides,
) -> SourceRevision:
    source = InfoSource(url=url, source_specs=[])
    session.add(source)
    await session.flush()
    revision = SourceRevision(
        info_source_id=source.info_source_id,
        content_fingerprint="sha256:" + fp * 64,
        captured_at=datetime.now(UTC),
        blob_fingerprint=digest,
        content_cache_uri=uri,
        **{"source_media_type": "text/html", **overrides},
    )
    session.add(revision)
    await session.flush()
    return revision


async def _count(session, model, *where) -> int:
    return (
        await session.execute(select(func.count()).select_from(model).where(*where))
    ).scalar_one()


async def _persist_outbox(session) -> list[ChangesOutboxRow]:
    result = await session.execute(
        select(ChangesOutboxRow).where(ChangesOutboxRow.topic == CONTENT_PERSIST)
    )
    return list(result.scalars().all())


# --- the switch ---


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(None, False), ("", False), ("0", False), ("no", False), ("1", True), (" TRUE ", True)],
)
def test_issuance_is_off_unless_switched_on(raw, expected):
    assert issuance_enabled(raw) is expected


@pytest.mark.asyncio
async def test_nothing_is_issued_while_switched_off(session, monkeypatch):
    monkeypatch.delenv(persist_issuance.ISSUANCE_ENV, raising=False)
    revision = await _revision(session)

    assert await issue_persist(session, revision) is None
    assert await _count(session, PersistCommand) == 0
    assert await _persist_outbox(session) == []


# --- issuing ---


@pytest.mark.asyncio
async def test_an_eligible_revision_gets_one_command_and_one_outbox_row(session, enabled):
    revision = await _revision(session)

    command = await issue_persist(session, revision)

    assert command is not None
    assert command.state == STATE_REQUESTED
    assert command.source_revision_id == revision.source_revision_id
    assert command.content_fingerprint == DIGEST
    assert command.blob_uri == BLOB_URI
    assert command.media_type == "text/html"
    [row] = await _persist_outbox(session)
    assert row.payload["command_id"] == command.command_id
    assert row.payload["content_fingerprint"] == DIGEST
    assert row.payload["blob_uri"] == BLOB_URI
    assert row.payload["media_type"] == "text/html"
    assert row.payload["event_type"] == "content_persist"


@pytest.mark.asyncio
async def test_an_unknown_media_type_is_sent_as_octet_stream(session, enabled):
    revision = await _revision(session, source_media_type=None)

    command = await issue_persist(session, revision)

    assert command.media_type == "application/octet-stream"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        {"digest": None},
        {"uri": None},
        {"persisted_at": datetime(2026, 9, 26, tzinfo=UTC)},
    ],
    ids=["no-digest", "no-blob", "already-persisted"],
)
async def test_an_ineligible_revision_is_not_issued(session, enabled, overrides):
    revision = await _revision(session, **overrides)

    assert await issue_persist(session, revision) is None
    assert await _count(session, PersistCommand) == 0


@pytest.mark.asyncio
async def test_an_open_command_for_the_same_bytes_suppresses_a_second(session, enabled):
    """Another source's revision with identical bytes: its success stamps both."""
    first = await _revision(session, url="https://example.com/one")
    second = await _revision(session, url="https://example.com/two", fp="b")
    await issue_persist(session, first)

    assert await issue_persist(session, second) is None
    assert await _count(session, PersistCommand) == 1


@pytest.mark.asyncio
async def test_a_closed_command_does_not_block_a_rearm(session, enabled):
    """Decision 3's retry path: after a terminal failure, the next occasion re-issues."""
    revision = await _revision(session)
    failed = await issue_persist(session, revision)
    failed.state = STATE_FAILED
    failed.closed_at = datetime.now(UTC)

    again = await issue_persist(session, revision)

    assert again is not None
    assert again.command_id != failed.command_id


@pytest.mark.asyncio
async def test_issuance_does_not_commit(session, enabled):
    revision = await _revision(session)
    await issue_persist(session, revision)

    await session.rollback()

    assert await _count(session, PersistCommand) == 0


# --- the reaper ---


async def _stale(session, revision, *, age: timedelta = HORIZON + timedelta(minutes=1)):
    command = await issue_persist(session, revision)
    command.issued_at = datetime.now(UTC) - age
    await session.flush()
    return command


@pytest.mark.asyncio
async def test_a_silent_command_is_abandoned_and_reissued(session, enabled):
    revision = await _revision(session)
    stale = await _stale(session, revision)

    abandoned, reissued = await reap_open_persists(session, horizon=HORIZON)

    assert (abandoned, reissued) == (1, 1)
    assert stale.state == STATE_ABANDONED
    assert stale.reason == REASON_NO_FACT
    assert stale.closed_at is not None
    fresh = (
        await session.execute(select(PersistCommand).where(PersistCommand.state == STATE_REQUESTED))
    ).scalar_one()
    assert fresh.command_id != stale.command_id
    assert fresh.content_fingerprint == DIGEST
    assert len(await _persist_outbox(session)) == 2


@pytest.mark.asyncio
async def test_a_recent_command_is_left_open(session, enabled):
    revision = await _revision(session)
    await _stale(session, revision, age=timedelta(minutes=5))

    assert await reap_open_persists(session, horizon=HORIZON) == (0, 0)


@pytest.mark.asyncio
async def test_switched_off_the_reaper_abandons_without_reissuing(session, enabled, monkeypatch):
    revision = await _revision(session)
    await _stale(session, revision)
    monkeypatch.delenv(persist_issuance.ISSUANCE_ENV)

    assert await reap_open_persists(session, horizon=HORIZON) == (1, 0)
    assert await _count(session, PersistCommand, PersistCommand.state == STATE_REQUESTED) == 0


@pytest.mark.asyncio
async def test_a_revision_persisted_meanwhile_is_not_reissued(session, enabled):
    """Another command for the same digest succeeded while this one was silent."""
    revision = await _revision(session)
    await _stale(session, revision)
    revision.persisted_at = datetime.now(UTC)

    assert await reap_open_persists(session, horizon=HORIZON) == (1, 0)


async def _raw_command(
    session, revision, *, state: str = STATE_REQUESTED, age: timedelta = HORIZON * 2
) -> PersistCommand:
    """A command row as an earlier pass left it, bypassing issuance's dedupe."""
    command = PersistCommand(
        command_id=f"pcmd-{await _count(session, PersistCommand)}",
        source_revision_id=revision.source_revision_id,
        content_fingerprint=revision.blob_fingerprint,
        blob_uri=revision.content_cache_uri,
        media_type="text/html",
        state=state,
        issued_at=datetime.now(UTC) - age,
        closed_at=None if state == STATE_REQUESTED else datetime.now(UTC) - age,
    )
    session.add(command)
    await session.flush()
    return command


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("prior_abandoned", "expected"), [(MAX_REISSUES - 1, (1, 1)), (MAX_REISSUES, (1, 0))]
)
async def test_reissues_stop_at_the_cap(session, enabled, prior_abandoned, expected):
    """A digest nothing ever answers gets MAX_REISSUES more tries, then is left
    abandoned rather than re-issued forever."""
    revision = await _revision(session)
    for _ in range(prior_abandoned):
        await _raw_command(session, revision, state=STATE_ABANDONED)
    await _raw_command(session, revision)

    assert await reap_open_persists(session, horizon=HORIZON) == expected


@pytest.mark.asyncio
async def test_two_silent_commands_for_one_digest_reissue_once(session, enabled):
    """Two revisions sharing bytes can each hold a command from before dedupe saw
    the other; one re-issue covers both, since a success stamps every revision."""
    first = await _revision(session, url="https://example.com/one")
    second = await _revision(session, url="https://example.com/two", fp="b")
    await _raw_command(session, first)
    await _raw_command(session, second)

    assert await reap_open_persists(session, horizon=HORIZON) == (2, 1)


@pytest.mark.asyncio
async def test_a_reissue_follows_the_digest_not_the_occasioning_revision(session, enabled):
    """The occasioning revision moved to new bytes (decision 2) and already holds
    a command for them; another revision still carries the abandoned digest and
    is the one to re-issue from (CR 9)."""
    moved = await _revision(session, url="https://example.com/moved")
    still = await _revision(
        session,
        url="https://example.com/still",
        fp="b",
        content_cache_expires_at=datetime.now(UTC) + timedelta(days=5),
    )
    await _raw_command(session, moved)
    moved.blob_fingerprint = OTHER_DIGEST
    moved.content_cache_uri = f"gs://co-gcs-blobs/blobs/{OTHER_DIGEST}.bin"
    await issue_persist(session, moved)

    assert await reap_open_persists(session, horizon=HORIZON) == (1, 1)
    reissue = (
        await session.execute(
            select(PersistCommand).where(
                PersistCommand.state == STATE_REQUESTED,
                PersistCommand.content_fingerprint == DIGEST,
            )
        )
    ).scalar_one()
    assert reissue.source_revision_id == still.source_revision_id


@pytest.mark.asyncio
async def test_a_persisted_command_is_never_reaped(session, enabled):
    revision = await _revision(session)
    command = await _stale(session, revision)
    command.state = STATE_PERSISTED
    command.closed_at = datetime.now(UTC)

    assert await reap_open_persists(session, horizon=HORIZON) == (0, 0)


# --- the permanent store ---


def test_the_permanent_uri_is_derived_from_the_digest():
    assert PERMANENT_BUCKET == "co-gcs-replicator"
    assert permanent_blob_uri(DIGEST) == f"gs://co-gcs-replicator/blobs/{DIGEST}.bin"
