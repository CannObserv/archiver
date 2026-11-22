"""The persist and replication reapers never overwrite an outcome being applied (archiver#496).

The same race #380 closed for captures (``test_capture_locking.py``, CR 1). A
reaper reads its stale ``requested`` rows, then writes ``abandoned`` to each.
Two orders of that against the ``content.artifacts`` consumer's writeback:

- **Consumer first.** The writeback has flushed its terminal state and holds the
  row lock, uncommitted. A plain read would see ``requested``, its UPDATE would
  wait for the lock, then write ``abandoned`` over the fresh outcome (and, for
  persist, re-issue its digest). ``FOR UPDATE SKIP LOCKED`` skips the row this
  tick; the next tick judges it on its committed state. Red without the fix:
  the reaper's UPDATE waits out ``lock_timeout``.
- **Reaper first.** The reaper holds the lock; the writeback, which loads its
  command unlocked, waits on its own UPDATE and lands after the reaper commits.
  Its terminal state overwrites ``abandoned`` by primary key, so the row ends
  truthful. For persist the re-issue stays in flight, a no-op on a
  content-addressed key. Pinned here as the accepted behaviour, not changed.

Both run on the real database, two sessions from one factory, rows committed.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from co_core.pure.adapters.bus.streams import CONTENT_PERSIST
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.core.models import (
    ChangesOutboxRow,
    InfoItem,
    InfoItemRepSpec,
    InfoSource,
    PersistCommand,
    ReplicationCommand,
    RepSpec,
    SourceRevision,
)
from src.core.services import persist_issuance
from src.core.services.persist_issuance import issue_persist, reap_open_persists
from src.core.services.persist_writeback import (
    STATE_ABANDONED,
    STATE_PERSISTED,
    STATE_REQUESTED,
    apply_persisted,
)
from src.core.services.replication_writeback import (
    STATE_COMPLETE,
    apply_success,
    reap_open_commands,
)

HORIZON = timedelta(hours=6)
STALE = HORIZON + timedelta(minutes=1)
DIGEST = "4" * 64  # unique to this module: the teardown keys on it
PUBLIC_URL = "https://storage.googleapis.com/co-archive/archive/lock-probe/x.html"


async def _backend_pid(session) -> int:
    return (await session.execute(text("SELECT pg_backend_pid()"))).scalar_one()


async def _wait_until_blocked(factory, pid: int, timeout: float = 5.0) -> None:
    """Return once backend ``pid`` waits on a lock, so the order under test holds.

    Keyed on the writer's own backend: another run's waiter must not stand in for it.
    """
    deadline = asyncio.get_running_loop().time() + timeout
    async with factory() as probe:
        while True:
            waiting = (
                await probe.execute(
                    text("SELECT count(*) FROM pg_locks WHERE pid = :pid AND NOT granted"),
                    {"pid": pid},
                )
            ).scalar_one()
            await probe.rollback()  # a fresh snapshot each poll; hold nothing
            if waiting:
                return
            if asyncio.get_running_loop().time() > deadline:
                raise AssertionError("the writeback never blocked on the reaper's lock")
            await asyncio.sleep(0.02)


# --- persist ---


@pytest.fixture
async def stale_persist(test_engine, monkeypatch):
    """A committed ``requested`` persist past the horizon, with a revision able to re-issue it."""
    monkeypatch.setenv(persist_issuance.ISSUANCE_ENV, "1")
    factory = async_sessionmaker(bind=test_engine, expire_on_commit=False)
    async with factory() as s:
        source = InfoSource(url="https://example.com/persist-lock-probe", source_specs=[])
        s.add(source)
        await s.flush()
        revision = SourceRevision(
            info_source_id=source.info_source_id,
            content_fingerprint="sha256:" + "5" * 64,
            captured_at=datetime.now(UTC),
            blob_fingerprint=DIGEST,
            content_cache_uri=f"gs://co-gcs-blobs/blobs/{DIGEST}.bin",
            source_media_type="text/html",
        )
        s.add(revision)
        await s.flush()
        command = await issue_persist(s, revision)
        command.issued_at = datetime.now(UTC) - STALE
        await s.commit()
    yield factory, command.command_id
    async with factory() as s:
        await s.execute(delete(PersistCommand).where(PersistCommand.content_fingerprint == DIGEST))
        await s.execute(
            delete(ChangesOutboxRow).where(
                ChangesOutboxRow.topic == CONTENT_PERSIST,
                ChangesOutboxRow.payload["content_fingerprint"].astext == DIGEST,
            )
        )
        await s.execute(
            delete(SourceRevision).where(SourceRevision.info_source_id == source.info_source_id)
        )
        await s.execute(
            delete(InfoSource).where(InfoSource.info_source_id == source.info_source_id)
        )
        await s.commit()


async def _persisted(session, command_id: str) -> None:
    await apply_persisted(
        session,
        command_id=command_id,
        content_fingerprint=DIGEST,
        size_bytes=1,
        occurred_at=datetime.now(UTC),
    )
    await session.flush()


@pytest.mark.asyncio
async def test_the_persist_reaper_skips_a_command_whose_outcome_is_being_applied(stale_persist):
    """Consumer first: no ``abandoned`` over a fresh ``persisted``, nor a re-issue of it."""
    factory, command_id = stale_persist
    async with factory() as persisting, factory() as reaping:
        await _persisted(persisting, command_id)  # holds the row lock, uncommitted
        await reaping.execute(text("SET LOCAL lock_timeout = '2s'"))

        assert await reap_open_persists(reaping, horizon=HORIZON) == (0, 0)

        await reaping.rollback()
        await persisting.commit()

    async with factory() as s:
        assert await reap_open_persists(s, horizon=HORIZON) == (0, 0)
        assert (await s.get(PersistCommand, command_id)).state == STATE_PERSISTED
        await s.rollback()


@pytest.mark.asyncio
async def test_a_persist_outcome_behind_the_reaper_lands_after_it(stale_persist):
    """Reaper first: the success waits, then overwrites ``abandoned``; the re-issue stays open."""
    factory, command_id = stale_persist
    async with factory() as reaping, factory() as persisting:
        assert await reap_open_persists(reaping, horizon=HORIZON) == (1, 1)  # holds the lock

        pid = await _backend_pid(persisting)

        async def _write() -> None:
            await _persisted(persisting, command_id)
            await persisting.commit()

        writing = asyncio.create_task(_write())
        await _wait_until_blocked(factory, pid)
        assert not writing.done()
        await reaping.commit()
        await asyncio.wait_for(writing, timeout=5)

    async with factory() as s:
        rows = (
            (
                await s.execute(
                    select(PersistCommand).where(PersistCommand.content_fingerprint == DIGEST)
                )
            )
            .scalars()
            .all()
        )
        states = {row.command_id: row.state for row in rows}
        assert states.pop(command_id) == STATE_PERSISTED
        assert list(states.values()) == [STATE_REQUESTED]  # the redundant re-issue
        assert STATE_ABANDONED not in states.values()
        await s.rollback()


# --- replication ---


@pytest.fixture
async def stale_replication(test_engine):
    """A committed ``requested`` replication command past the horizon."""
    factory = async_sessionmaker(bind=test_engine, expire_on_commit=False)
    command_id = "cmd-reaper-lock-probe"
    async with factory() as s:
        source = InfoSource(url="https://example.com/replication-lock-probe", source_specs=[])
        item = InfoItem(name="replication-lock-probe", rep_fields={})
        spec = RepSpec(provider="gcs", name="replication-lock-probe", schema_version=1, document={})
        s.add_all([source, item, spec])
        await s.flush()
        assignment = InfoItemRepSpec(
            info_item_id=item.info_item_id,
            rep_spec_id=spec.rep_spec_id,
            activated_at=datetime.now(UTC),
        )
        revision = SourceRevision(
            info_source_id=source.info_source_id,
            content_fingerprint="sha256:" + "6" * 64,
            captured_at=datetime.now(UTC),
        )
        s.add_all([assignment, revision])
        await s.flush()
        s.add(
            ReplicationCommand(
                command_id=command_id,
                info_item_rep_spec_id=assignment.id,
                source_revision_id=revision.source_revision_id,
                info_source_id=source.info_source_id,
                provider="gcs",
                credentials_alias="alias",
                destination="archive/lock-probe/x.html",
                media_type="text/html",
                blob_uri="file:///blobs/x.bin",
                state=STATE_REQUESTED,
                issued_at=datetime.now(UTC) - STALE,
            )
        )
        await s.commit()
    yield factory, command_id
    async with factory() as s:
        await s.execute(
            delete(ReplicationCommand).where(ReplicationCommand.command_id == command_id)
        )
        await s.execute(delete(InfoItem).where(InfoItem.info_item_id == item.info_item_id))
        await s.execute(delete(RepSpec).where(RepSpec.rep_spec_id == spec.rep_spec_id))
        await s.execute(
            delete(SourceRevision).where(SourceRevision.info_source_id == source.info_source_id)
        )
        await s.execute(
            delete(InfoSource).where(InfoSource.info_source_id == source.info_source_id)
        )
        await s.commit()


async def _complete(session, command_id: str) -> None:
    await apply_success(
        session, command_id=command_id, public_url=PUBLIC_URL, occurred_at=datetime.now(UTC)
    )
    await session.flush()


@pytest.mark.asyncio
async def test_the_replication_reaper_skips_a_command_whose_outcome_is_being_applied(
    stale_replication,
):
    """Consumer first: no ``abandoned`` over a fresh ``complete``."""
    factory, command_id = stale_replication
    async with factory() as completing, factory() as reaping:
        await _complete(completing, command_id)  # holds the row lock, uncommitted
        await reaping.execute(text("SET LOCAL lock_timeout = '2s'"))

        assert await reap_open_commands(reaping, horizon=HORIZON) == 0

        await reaping.rollback()
        await completing.commit()

    async with factory() as s:
        assert await reap_open_commands(s, horizon=HORIZON) == 0
        assert (await s.get(ReplicationCommand, command_id)).state == STATE_COMPLETE
        await s.rollback()


@pytest.mark.asyncio
async def test_a_replication_outcome_behind_the_reaper_lands_after_it(stale_replication):
    """Reaper first: the success waits, then overwrites ``abandoned`` by primary key.

    No flush before the writeback starts: ``reap_open_commands`` leaves its abandon
    pending, so the only lock is the select's. Without it the writeback would not
    wait; it would commit ``complete`` in the gap, and the reaper's later UPDATE
    would write ``abandoned`` over it - the issue's race, closed by ``FOR UPDATE``.
    """
    factory, command_id = stale_replication
    async with factory() as reaping, factory() as completing:
        assert await reap_open_commands(reaping, horizon=HORIZON) == 1  # select-locked

        pid = await _backend_pid(completing)

        async def _write() -> None:
            await _complete(completing, command_id)
            await completing.commit()

        writing = asyncio.create_task(_write())
        await _wait_until_blocked(factory, pid)
        assert not writing.done()
        await reaping.commit()
        await asyncio.wait_for(writing, timeout=5)

    async with factory() as s:
        row = await s.get(ReplicationCommand, command_id)
        assert row.state == STATE_COMPLETE
        assert row.public_url == PUBLIC_URL
        await s.rollback()
