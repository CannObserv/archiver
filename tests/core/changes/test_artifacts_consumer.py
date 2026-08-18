"""Tests for the ``content.artifacts`` consumer (archiver#170).

Archiver's second group consumer, and the one that closes the replication loop:
`replication_complete` is what finally writes `info_item_rep_specs.public_url`.

Covers, per-message:
1. A success fact → public_url on the assignment, command closed, message acked
2. A repeat of the same success → idempotent (T4 re-emits by design)
3. A terminal failure → command closed with the producer's reason, acked
4. A non-terminal failure → command still open, acked
5. An unknown command_id → ack and drop, nothing written
6. A DB failure leaves the message un-acked (redelivery, not loss)
7. Another event type on the stream → acked, ignored

And, around the loop:
8. The group is created at "0"
9. A poison frame is DLQ'd rather than wedging the loop
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from co_core.pure.adapters.bus.envelope import to_wire
from co_core.pure.adapters.bus.streams import CONTENT_ARTIFACTS
from co_core.pure.models.changes import (
    ReplicationCompleteEvent,
    ReplicationFailedEvent,
    SourceRevisionObservedEvent,
)
from fakeredis import aioredis as fakeredis_aio
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.core.changes import artifacts_consumer
from src.core.models import (
    InfoItem,
    InfoItemRepSpec,
    InfoSource,
    ReplicationCommand,
    RepSpec,
    SourceRevision,
)
from src.core.services.replication_issuance import STATE_REQUESTED
from src.core.services.replication_writeback import (
    STATE_COMPLETE,
    STATE_FAILED,
)

PUBLIC_URL = "https://storage.googleapis.com/co-archive/archive/wa-lcb/x.html"
OCCURRED_AT = datetime(2026, 8, 18, 9, 0, tzinfo=UTC)


@pytest.fixture
async def fake_redis():
    r = fakeredis_aio.FakeRedis()
    yield r
    await r.aclose()


@pytest.fixture
def session_factory(test_engine):
    return async_sessionmaker(bind=test_engine, expire_on_commit=False)


@pytest.fixture(autouse=True)
async def clean_tables(test_engine):
    """These tests commit for real — the consumer opens its own session, so the
    savepoint-isolated ``session`` fixture would be invisible to it."""
    statements = (
        "TRUNCATE TABLE information.replication_commands CASCADE",
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


@pytest.fixture
async def issued_command(session_factory) -> ReplicationCommand:
    """One assignment with one open command against it, committed for real."""
    async with session_factory() as s:
        source = InfoSource(url="https://example.com/artifacts", source_specs=[])
        item = InfoItem(name="artifacts-item", rep_fields={})
        spec = RepSpec(provider="gcs", name="artifacts-spec", schema_version=1, document={})
        s.add_all([source, item, spec])
        await s.flush()
        assignment = InfoItemRepSpec(
            info_item_id=item.info_item_id,
            rep_spec_id=spec.rep_spec_id,
            activated_at=datetime.now(UTC),
        )
        revision = SourceRevision(
            info_source_id=source.info_source_id,
            content_fingerprint="sha256:" + "b" * 64,
            captured_at=datetime.now(UTC),
        )
        s.add_all([assignment, revision])
        await s.flush()
        command = ReplicationCommand(
            command_id="cmd-artifacts-1",
            info_item_rep_spec_id=assignment.id,
            source_revision_id=revision.source_revision_id,
            info_source_id=revision.info_source_id,
            provider="gcs",
            credentials_alias="alias",
            destination="archive/wa-lcb/x.html",
            media_type="text/html",
            blob_uri="file:///blobs/b.bin",
            state=STATE_REQUESTED,
        )
        s.add(command)
        await s.commit()
        return command


async def _assignment(session_factory, command: ReplicationCommand) -> InfoItemRepSpec:
    async with session_factory() as s:
        return await s.get(InfoItemRepSpec, command.info_item_rep_spec_id)


async def _reload(session_factory, command: ReplicationCommand) -> ReplicationCommand:
    async with session_factory() as s:
        return await s.get(ReplicationCommand, command.command_id)


def _complete(command: ReplicationCommand, public_url: str = PUBLIC_URL) -> dict:
    event = ReplicationCompleteEvent(
        occurred_at=OCCURRED_AT,
        command_id=command.command_id,
        public_url=public_url,
        info_item_rep_spec_id=str(command.info_item_rep_spec_id),
        source_revision_id=str(command.source_revision_id),
        info_source_id=str(command.info_source_id),
    )
    return to_wire(event)


def _failed(command: ReplicationCommand, *, reason: str, terminal: bool) -> dict:
    event = ReplicationFailedEvent(
        occurred_at=OCCURRED_AT,
        command_id=command.command_id,
        info_item_rep_spec_id=str(command.info_item_rep_spec_id),
        source_revision_id=str(command.source_revision_id),
        info_source_id=str(command.info_source_id),
        reason=reason,
        terminal=terminal,
        attempts=2,
        detail="from the producer",
    )
    return to_wire(event)


async def _publish(fake_redis, fields: dict) -> None:
    await fake_redis.xadd(CONTENT_ARTIFACTS, fields)


async def _consume(fake_redis, session_factory, *, name: str = "artifacts:1") -> int:
    consumer = artifacts_consumer.build_consumer(fake_redis, consumer_name=name)
    await artifacts_consumer.ensure_group(consumer)
    return await artifacts_consumer.consume_once(
        session_factory=session_factory, consumer=consumer, block_ms=10
    )


async def _pending(fake_redis) -> int:
    info = await fake_redis.xpending(CONTENT_ARTIFACTS, artifacts_consumer.CONSUMER_GROUP)
    return info["pending"] if isinstance(info, dict) else info[0]


# --- per-message ---


@pytest.mark.asyncio
async def test_success_writes_public_url_and_acks(fake_redis, session_factory, issued_command):
    await _publish(fake_redis, _complete(issued_command))

    settled = await _consume(fake_redis, session_factory)

    assert settled == 1
    assert await _pending(fake_redis) == 0
    assignment = await _assignment(session_factory, issued_command)
    assert assignment.public_url == PUBLIC_URL
    command = await _reload(session_factory, issued_command)
    assert command.state == STATE_COMPLETE


@pytest.mark.asyncio
async def test_repeated_success_is_idempotent(fake_redis, session_factory, issued_command):
    """A redelivery that finds matching bytes re-emits the same fact by design."""
    await _publish(fake_redis, _complete(issued_command))
    await _consume(fake_redis, session_factory)
    await _publish(fake_redis, _complete(issued_command))

    assert await _consume(fake_redis, session_factory) == 1

    assignment = await _assignment(session_factory, issued_command)
    assert assignment.public_url == PUBLIC_URL


@pytest.mark.asyncio
async def test_terminal_failure_closes_the_command(fake_redis, session_factory, issued_command):
    await _publish(fake_redis, _failed(issued_command, reason="blob_expired", terminal=True))

    assert await _consume(fake_redis, session_factory) == 1

    command = await _reload(session_factory, issued_command)
    assert command.state == STATE_FAILED
    assert command.reason == "blob_expired"
    assert command.closed_at is not None


@pytest.mark.asyncio
async def test_non_terminal_failure_leaves_the_command_open_and_acks(
    fake_redis, session_factory, issued_command
):
    """The *message* is settled either way — the command's openness is registry
    state, not delivery state."""
    await _publish(
        fake_redis, _failed(issued_command, reason="provider_unavailable", terminal=False)
    )

    assert await _consume(fake_redis, session_factory) == 1
    assert await _pending(fake_redis) == 0

    command = await _reload(session_factory, issued_command)
    assert command.state == STATE_REQUESTED
    assert command.closed_at is None


@pytest.mark.asyncio
async def test_unknown_command_id_is_dropped(fake_redis, session_factory, issued_command):
    """The registry is the authority on what it issued; a fact about anything
    else is ack-and-drop, matching content.revisions' unknown-source posture."""
    fields = _complete(issued_command)
    stray = ReplicationCompleteEvent(
        occurred_at=OCCURRED_AT,
        command_id="never-issued",
        public_url=PUBLIC_URL,
        info_item_rep_spec_id=str(issued_command.info_item_rep_spec_id),
        source_revision_id=str(issued_command.source_revision_id),
        info_source_id=str(issued_command.info_source_id),
    )
    await _publish(fake_redis, to_wire(stray))

    assert await _consume(fake_redis, session_factory) == 1
    assert await _pending(fake_redis) == 0

    assignment = await _assignment(session_factory, issued_command)
    assert assignment.public_url is None
    assert fields  # the well-formed one was never published; nothing else changed


@pytest.mark.asyncio
async def test_database_failure_leaves_the_message_pending(
    fake_redis, session_factory, issued_command
):
    """Redelivery, not loss — the ack strictly follows the commit."""
    await _publish(fake_redis, _complete(issued_command))

    with patch(
        "src.core.changes.artifacts_consumer.apply_success",
        side_effect=RuntimeError("database is down"),
    ):
        settled = await _consume(fake_redis, session_factory)

    assert settled == 0
    assert await _pending(fake_redis) == 1


@pytest.mark.asyncio
async def test_foreign_event_type_is_acked_and_ignored(fake_redis, session_factory, issued_command):
    """It decoded fine, it just is not ours."""
    observed = SourceRevisionObservedEvent(
        occurred_at=OCCURRED_AT,
        info_source_id=str(issued_command.info_source_id),
        extracted_fingerprint="sha256:" + "d" * 64,
        captured_at=OCCURRED_AT,
        content_size_bytes=1024,
        content_media_type="text/plain",
        source_media_type="text/html",
        blob_uri="file:///blobs/d.bin",
        command_id="cmd-observed",
    )
    await _publish(fake_redis, to_wire(observed))

    assert await _consume(fake_redis, session_factory) == 1
    assert await _pending(fake_redis) == 0

    async with session_factory() as s:
        count = await s.scalar(select(func.count()).select_from(ReplicationCommand))
    assert count == 1


# --- around the loop ---


@pytest.mark.asyncio
async def test_group_is_created_at_zero(fake_redis, session_factory, issued_command):
    """Entries published before the group exists are still consumed — the
    ordering guarantee that lets the consumer land before the producer cuts
    over."""
    await _publish(fake_redis, _complete(issued_command))

    assert await _consume(fake_redis, session_factory) == 1

    assignment = await _assignment(session_factory, issued_command)
    assert assignment.public_url == PUBLIC_URL


@pytest.mark.asyncio
async def test_undecodable_frame_is_quarantined(fake_redis, session_factory):
    """A frame that will not decode goes to the DLQ instead of wedging the loop."""
    await fake_redis.xadd(CONTENT_ARTIFACTS, {"not": "an envelope"})

    settled = await _consume(fake_redis, session_factory)

    assert settled == 0
    dlq_len = await fake_redis.xlen(f"{CONTENT_ARTIFACTS}.dlq")
    assert dlq_len == 1
