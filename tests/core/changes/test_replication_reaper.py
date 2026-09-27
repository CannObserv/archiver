"""The replication reaper timer (archiver#170).

MUST-6's obligation. It runs on a clock rather than off an arrival because the
condition it detects is the *absence* of a message — a provider 5xx that
Replicator retries unboundedly publishes no fact at all while it does.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from co_core.pure.adapters.bus.streams import CONTENT_PERSIST
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.core.changes import replication_reaper
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
from src.core.services.replication_issuance import STATE_REQUESTED
from src.core.services.replication_writeback import STATE_ABANDONED


@pytest.fixture
def session_factory(test_engine):
    return async_sessionmaker(bind=test_engine, expire_on_commit=False)


@pytest.fixture(autouse=True)
async def clean_tables(test_engine):
    statements = (
        "TRUNCATE TABLE information.replication_commands CASCADE",
        "TRUNCATE TABLE information.persist_commands CASCADE",
        "TRUNCATE TABLE information.changes_outbox CASCADE",
        "TRUNCATE TABLE information.info_item_rep_specs CASCADE",
        "TRUNCATE TABLE information.source_revisions CASCADE",
        "TRUNCATE TABLE information.info_items CASCADE",
        "TRUNCATE TABLE information.rep_specs CASCADE",
        "TRUNCATE TABLE information.info_sources CASCADE",
    )
    async with test_engine.begin() as conn:
        for statement in statements:
            await conn.execute(text(statement))
    yield
    async with test_engine.begin() as conn:
        for statement in statements:
            await conn.execute(text(statement))


async def _open_command(session_factory, *, age: timedelta) -> str:
    async with session_factory() as s:
        source = InfoSource(url="https://example.com/reaper", source_specs=[])
        item = InfoItem(name="reaper-item", rep_fields={})
        spec = RepSpec(provider="gcs", name="reaper-spec", schema_version=1, document={})
        s.add_all([source, item, spec])
        await s.flush()
        assignment = InfoItemRepSpec(
            info_item_id=item.info_item_id,
            rep_spec_id=spec.rep_spec_id,
            activated_at=datetime.now(UTC),
        )
        revision = SourceRevision(
            info_source_id=source.info_source_id,
            content_fingerprint="sha256:" + "e" * 64,
            captured_at=datetime.now(UTC),
        )
        s.add_all([assignment, revision])
        await s.flush()
        command = ReplicationCommand(
            command_id="cmd-reaper-1",
            info_item_rep_spec_id=assignment.id,
            source_revision_id=revision.source_revision_id,
            info_source_id=revision.info_source_id,
            provider="gcs",
            credentials_alias="alias",
            destination="archive/x.html",
            media_type="text/html",
            state=STATE_REQUESTED,
            issued_at=datetime.now(UTC) - age,
        )
        s.add(command)
        await s.commit()
        return command.command_id


async def _state(session_factory, command_id: str) -> str:
    async with session_factory() as s:
        command = await s.get(ReplicationCommand, command_id)
        return command.state


# --- knobs ---


def test_interval_defaults_when_unset_or_malformed():
    assert replication_reaper.resolve_interval(None) == replication_reaper.DEFAULT_INTERVAL_SECONDS
    assert (
        replication_reaper.resolve_interval("banana") == replication_reaper.DEFAULT_INTERVAL_SECONDS
    )


def test_interval_is_clamped_to_its_floor():
    """A malformed knob degrades the sweep; it never disables the safety net."""
    assert replication_reaper.resolve_interval("1") == 60.0


def test_horizon_parses_seconds_and_clamps():
    assert replication_reaper.resolve_horizon("7200") == timedelta(hours=2)
    assert replication_reaper.resolve_horizon("5") == timedelta(seconds=300)
    assert replication_reaper.resolve_horizon(None) == timedelta(hours=6)


# --- sweeping ---


@pytest.mark.asyncio
async def test_sweep_commits_the_abandonment(session_factory):
    command_id = await _open_command(session_factory, age=timedelta(hours=9))

    reaped = await replication_reaper.sweep_once(session_factory, horizon=timedelta(hours=6))

    assert reaped == 1
    assert await _state(session_factory, command_id) == STATE_ABANDONED


@pytest.mark.asyncio
async def test_sweep_leaves_a_recent_command_open(session_factory):
    command_id = await _open_command(session_factory, age=timedelta(minutes=5))

    assert await replication_reaper.sweep_once(session_factory, horizon=timedelta(hours=6)) == 0
    assert await _state(session_factory, command_id) == STATE_REQUESTED


@pytest.mark.asyncio
async def test_run_sweeps_once_at_startup_then_waits(session_factory):
    """A process that crashed mid-outage comes back to a backlog already past
    the horizon; waiting a full period to notice serves nobody."""
    command_id = await _open_command(session_factory, age=timedelta(hours=9))
    stop = asyncio.Event()

    task = asyncio.create_task(
        replication_reaper.run(
            session_factory=session_factory,
            stop_event=stop,
            interval=3600.0,
            horizon=timedelta(hours=6),
        )
    )
    for _ in range(100):
        await asyncio.sleep(0.01)
        if await _state(session_factory, command_id) == STATE_ABANDONED:
            break
    stop.set()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert await _state(session_factory, command_id) == STATE_ABANDONED


@pytest.mark.asyncio
async def test_a_failing_sweep_does_not_kill_the_loop(session_factory, monkeypatch):
    """The reaper is a safety net; one bad pass must not remove it."""
    calls = {"n": 0}

    async def _boom(*_args, **_kwargs):
        calls["n"] += 1
        raise RuntimeError("database is down")

    monkeypatch.setattr(replication_reaper, "sweep_once", _boom)
    stop = asyncio.Event()
    task = asyncio.create_task(
        replication_reaper.run(
            session_factory=session_factory,
            stop_event=stop,
            interval=0.01,
            horizon=timedelta(hours=6),
            error_backoff_base=0.01,
        )
    )
    await asyncio.sleep(0.05)
    stop.set()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert calls["n"] >= 1
    assert task.done()


# --- persist commands (archiver#276 PR C) ---


async def _open_persist(session_factory, *, age: timedelta) -> str:
    async with session_factory() as s:
        source = InfoSource(url="https://example.com/persist-reaper", source_specs=[])
        s.add(source)
        await s.flush()
        revision = SourceRevision(
            info_source_id=source.info_source_id,
            content_fingerprint="sha256:" + "f" * 64,
            captured_at=datetime.now(UTC),
            blob_fingerprint="f" * 64,
            content_cache_uri="gs://co-gcs-blobs/blobs/" + "f" * 64 + ".bin",
        )
        s.add(revision)
        await s.flush()
        command = PersistCommand(
            command_id="pcmd-reaper-1",
            source_revision_id=revision.source_revision_id,
            content_fingerprint=revision.blob_fingerprint,
            blob_uri=revision.content_cache_uri,
            media_type="text/html",
            state=STATE_REQUESTED,
            issued_at=datetime.now(UTC) - age,
        )
        s.add(command)
        await s.commit()
        return command.command_id


@pytest.mark.asyncio
async def test_the_sweep_reissues_a_silent_persist_and_commits(session_factory, monkeypatch):
    """The same timer serves persist: its condition is also an absence (P3)."""
    monkeypatch.setenv(persist_issuance.ISSUANCE_ENV, "1")
    command_id = await _open_persist(session_factory, age=timedelta(hours=9))

    await replication_reaper.sweep_once(session_factory, horizon=timedelta(hours=6))

    async with session_factory() as s:
        states = {
            c.command_id: c.state for c in (await s.execute(select(PersistCommand))).scalars()
        }
        outbox = (
            await s.execute(
                select(func.count())
                .select_from(ChangesOutboxRow)
                .where(ChangesOutboxRow.topic == CONTENT_PERSIST)
            )
        ).scalar_one()
    assert states.pop(command_id) == STATE_ABANDONED
    assert list(states.values()) == [STATE_REQUESTED]
    assert outbox == 1


@pytest.mark.asyncio
async def test_a_failing_persist_sweep_does_not_cost_replication_its_reaping(
    session_factory, monkeypatch
):
    """MUST-6's safety net must survive a defect in the newer persist half (CR 10)."""
    command_id = await _open_command(session_factory, age=timedelta(hours=9))

    async def _boom(*_args, **_kwargs):
        raise RuntimeError("persist sweep defect")

    monkeypatch.setattr(persist_issuance, "reap_open_persists", _boom)

    reaped = await replication_reaper.sweep_once(session_factory, horizon=timedelta(hours=6))

    assert reaped == 1
    assert await _state(session_factory, command_id) == STATE_ABANDONED
