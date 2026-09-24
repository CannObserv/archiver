"""DLQ reprocess: run archiver's own handler on a parked entry, then XDEL it (archiver#238).

The handlers commit for real, so these tests use a session factory on the test
engine and truncate what they write (the ``test_consumer`` precedent). The
stream commands run against fakeredis.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from co_core.pure.adapters.bus.dead_letter import dead_letter_fields
from co_core.pure.adapters.bus.envelope import to_wire
from co_core.pure.adapters.bus.streams import CONTENT_REVISIONS
from co_core.pure.models.changes import ReplicationCompleteEvent, SourceRevisionObservedEvent
from fakeredis import aioredis as fakeredis_aio
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker
from ulid import ULID

from src.core.changes import artifacts_consumer, dlq_triage
from src.core.changes.dlq_triage import (
    TRIAGE_DLQS,
    ReprocessInterruptedError,
    ReprocessResult,
    reprocess_dead_letters,
)
from src.core.models import InfoSource, SourceRevision

REVISIONS_DLQ = "content.revisions.dlq"
OWN_GROUP = "archiver.revisions"


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
    """The handlers commit for real; nothing they write may leak between tests."""
    yield
    async with test_engine.begin() as conn:
        await conn.execute(text("TRUNCATE TABLE information.changes_outbox"))
        await conn.execute(text("TRUNCATE TABLE information.source_revisions CASCADE"))


@pytest.fixture
async def info_source(session_factory) -> AsyncGenerator[InfoSource]:
    """A committed InfoSource - the handler opens its own session.

    Deleted by id on teardown, its revisions first, rather than truncated:
    other modules' rows in the shared test database are not this fixture's to
    remove.
    """
    async with session_factory() as s:
        src = InfoSource(
            url="https://example.com/dlq-reprocess",
            source_specs=[
                {"schema_version": 1, "extraction": {"algorithm": "full_page"}, "fingerprint": {}}
            ],
        )
        s.add(src)
        await s.commit()
    yield src
    async with session_factory() as s:
        await s.execute(
            delete(SourceRevision).where(SourceRevision.info_source_id == src.info_source_id)
        )
        await s.execute(delete(InfoSource).where(InfoSource.info_source_id == src.info_source_id))
        await s.commit()


def _observed(info_source_id, fingerprint: str = "sha256:" + "b" * 64) -> dict[str, str]:
    return to_wire(
        SourceRevisionObservedEvent(
            occurred_at=datetime(2026, 9, 24, 12, 0, tzinfo=UTC),
            info_source_id=str(info_source_id),
            extracted_fingerprint=fingerprint,
            captured_at=datetime(2026, 9, 24, 11, 59, tzinfo=UTC),
            content_size_bytes=2048,
            content_media_type="text/plain",
            source_media_type="text/html",
            blob_uri="file:///var/lib/replicator/blobs/ab/cd/deadbeef.bin",
            command_id="cmd-reprocess",
        )
    )


def _parked(frame: dict[str, str], *, group: str = OWN_GROUP, source_id: str = "1-0") -> dict:
    return dead_letter_fields(
        frame,
        source_id=source_id,
        group=group,
        consumer=f"{group.replace('.', '-')}-1",
        reason="undecodable: BusMessageUnknownEventTypeError('source_revision_observed')",
    )


async def _park(fake_redis, fields: dict[str, str]) -> str:
    return (await fake_redis.xadd(REVISIONS_DLQ, fields)).decode()


async def _revisions(session_factory) -> int:
    async with session_factory() as s:
        return (await s.execute(select(func.count()).select_from(SourceRevision))).scalar_one()


def _spy(outcome: bool | BaseException, seen: list):
    """A reprocessor whose handler records the message it was handed."""

    async def handle(_session_factory, message) -> bool:
        seen.append(message)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    return dlq_triage._Reprocessor(handle=handle, poison_errors=(ValueError,))


def test_every_triaged_queue_has_a_reprocessor():
    """A new owned group joins TRIAGE_DLQS automatically; this is what makes it
    bring its handler too, rather than failing a reprocess with a KeyError."""
    assert set(dlq_triage._REPROCESSORS) == set(TRIAGE_DLQS)


async def test_a_skew_frame_is_recorded_by_the_real_handler_and_removed(
    fake_redis, session_factory, info_source
):
    """The case reprocess exists for: parked as undecodable, decodes now."""
    entry_id = await _park(fake_redis, _parked(_observed(info_source.info_source_id)))

    results = await reprocess_dead_letters(
        fake_redis, REVISIONS_DLQ, [entry_id], session_factory=session_factory
    )

    assert results == (ReprocessResult(entry_id=entry_id, outcome="reprocessed", detail=None),)
    assert await _revisions(session_factory) == 1
    assert await fake_redis.xlen(REVISIONS_DLQ) == 0


async def test_the_handler_gets_the_wire_half_under_the_original_id(fake_redis, session_factory):
    """Provenance never reaches the handler, and its log lines name the id the
    source stream knew the frame by."""
    seen: list = []
    entry_id = await _park(
        fake_redis, _parked(_observed("01J0000000000000000000000A"), source_id="42-7")
    )

    with patch.dict(dlq_triage._REPROCESSORS, {REVISIONS_DLQ: _spy(True, seen)}):
        await reprocess_dead_letters(
            fake_redis, REVISIONS_DLQ, [entry_id], session_factory=session_factory
        )

    [message] = seen
    assert message.message_id == "42-7"
    assert not [k for k in message.fields if k.startswith("dlq.")]
    assert message.topic == CONTENT_REVISIONS


@pytest.mark.parametrize(
    ("group", "detail"),
    [
        ("notifier.revisions", "parked by 'notifier.revisions'"),
        ("archiver.artifacts", "parked by 'archiver.artifacts'"),
    ],
)
async def test_an_entry_another_group_parked_is_left_alone(
    fake_redis, session_factory, info_source, group, detail
):
    """A fact stream's DLQ is shared (cannobserv#474): archiver's handler has no
    business deciding another consumer's dead letter."""
    entry_id = await _park(fake_redis, _parked(_observed(info_source.info_source_id), group=group))

    [result] = await reprocess_dead_letters(
        fake_redis, REVISIONS_DLQ, [entry_id], session_factory=session_factory
    )

    assert result.outcome == "not_owned"
    assert detail in result.detail
    assert await _revisions(session_factory) == 0
    assert await fake_redis.xlen(REVISIONS_DLQ) == 1


async def test_an_entry_with_no_provenance_is_left_alone(fake_redis, session_factory, info_source):
    """Written before co-core 0.19.1: nothing proves archiver's group parked it."""
    entry_id = await _park(fake_redis, _observed(info_source.info_source_id))

    [result] = await reprocess_dead_letters(
        fake_redis, REVISIONS_DLQ, [entry_id], session_factory=session_factory
    )

    assert result.outcome == "not_owned"
    assert "no provenance" in result.detail
    assert await fake_redis.xlen(REVISIONS_DLQ) == 1


async def test_a_frame_that_still_does_not_decode_stays(fake_redis, session_factory):
    entry_id = await _park(fake_redis, _parked({"event_type": "not_yet", "payload": "{}"}))

    [result] = await reprocess_dead_letters(
        fake_redis, REVISIONS_DLQ, [entry_id], session_factory=session_factory
    )

    assert result.outcome == "undecodable"
    assert "BusMessageUnknownEventTypeError" in result.detail
    assert await fake_redis.xlen(REVISIONS_DLQ) == 1


async def test_handler_poison_is_rejected_and_stays(fake_redis, session_factory, info_source):
    """The real revisions handler's POISON_ERRORS: a reprocess cannot fix
    deterministic producer data, so the entry waits for a discard."""
    entry_id = await _park(
        fake_redis, _parked(_observed(info_source.info_source_id, fingerprint="deadbeef"))
    )

    [result] = await reprocess_dead_letters(
        fake_redis, REVISIONS_DLQ, [entry_id], session_factory=session_factory
    )

    assert result.outcome == "rejected"
    assert "InvalidFingerprintError" in result.detail
    assert await _revisions(session_factory) == 0
    assert await fake_redis.xlen(REVISIONS_DLQ) == 1


async def test_a_failing_handler_leaves_its_entry_and_the_rest_still_run(
    fake_redis, session_factory
):
    """A transient failure (the database down) is per entry: report it, keep the
    entry, carry on - the operator retries once it clears."""
    seen: list = []
    first = await _park(
        fake_redis, _parked(_observed("01J0000000000000000000000A"), source_id="1-0")
    )
    second = await _park(
        fake_redis, _parked(_observed("01J0000000000000000000000B"), source_id="2-0")
    )

    with patch.dict(
        dlq_triage._REPROCESSORS, {REVISIONS_DLQ: _spy(RuntimeError("database down"), seen)}
    ):
        results = await reprocess_dead_letters(
            fake_redis, REVISIONS_DLQ, [first, second], session_factory=session_factory
        )

    assert [r.outcome for r in results] == ["failed", "failed"]
    assert "database down" in results[0].detail
    assert len(seen) == 2
    assert await fake_redis.xlen(REVISIONS_DLQ) == 2


async def test_a_handler_asking_for_redelivery_leaves_the_entry(fake_redis, session_factory):
    """``False`` is the MessageHandler contract's "not settled": nothing to delete."""
    entry_id = await _park(fake_redis, _parked(_observed("01J0000000000000000000000A")))

    with patch.dict(dlq_triage._REPROCESSORS, {REVISIONS_DLQ: _spy(False, [])}):
        [result] = await reprocess_dead_letters(
            fake_redis, REVISIONS_DLQ, [entry_id], session_factory=session_factory
        )

    assert result.outcome == "deferred"
    assert await fake_redis.xlen(REVISIONS_DLQ) == 1


async def test_an_id_not_in_the_queue_is_not_found(fake_redis, session_factory):
    [result] = await reprocess_dead_letters(
        fake_redis, REVISIONS_DLQ, ["1-0"], session_factory=session_factory
    )
    assert result == ReprocessResult(entry_id="1-0", outcome="not_found", detail=None)


async def test_inexact_ids_are_refused_before_anything_runs(fake_redis, session_factory):
    seen: list = []
    entry_id = await _park(fake_redis, _parked(_observed("01J0000000000000000000000A")))

    with patch.dict(dlq_triage._REPROCESSORS, {REVISIONS_DLQ: _spy(True, seen)}):
        with pytest.raises(ValueError, match="stream id"):
            await reprocess_dead_letters(
                fake_redis, REVISIONS_DLQ, [entry_id, "+"], session_factory=session_factory
            )

    assert seen == []
    assert await fake_redis.xlen(REVISIONS_DLQ) == 1


async def test_a_broker_failure_on_the_delete_names_the_entry_in_doubt(fake_redis, session_factory):
    """The handler's write committed; only the XDEL is in doubt. A retry would
    reprocess it again, which the handlers' idempotency makes harmless."""
    first = await _park(
        fake_redis, _parked(_observed("01J0000000000000000000000A"), source_id="1-0")
    )
    second = await _park(
        fake_redis, _parked(_observed("01J0000000000000000000000B"), source_id="2-0")
    )
    real_xdel = fake_redis.xdel
    calls = 0

    async def xdel_then_fail(*args):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RedisConnectionError("broker went away")
        return await real_xdel(*args)

    with (
        patch.dict(dlq_triage._REPROCESSORS, {REVISIONS_DLQ: _spy(True, [])}),
        patch.object(fake_redis, "xdel", xdel_then_fail),
        pytest.raises(ReprocessInterruptedError) as caught,
    ):
        await reprocess_dead_letters(
            fake_redis, REVISIONS_DLQ, [first, second], session_factory=session_factory
        )

    assert caught.value.results == (
        ReprocessResult(entry_id=first, outcome="reprocessed", detail=None),
    )
    assert caught.value.in_doubt == second
    assert isinstance(caught.value.__cause__, RedisConnectionError)


async def test_reprocess_logs_each_frame_before_deleting_it(fake_redis, session_factory):
    """The same audit record discard leaves: the frame, before it is gone."""
    order: list[str] = []
    entry_id = await _park(fake_redis, _parked(_observed("01J0000000000000000000000A")))
    real_xdel = fake_redis.xdel

    async def spy_xdel(*args):
        order.append("xdel")
        return await real_xdel(*args)

    with (
        patch.dict(dlq_triage._REPROCESSORS, {REVISIONS_DLQ: _spy(True, [])}),
        patch.object(
            dlq_triage.logger, "info", side_effect=lambda *a, **k: order.append(a[0])
        ) as info,
        patch.object(fake_redis, "xdel", spy_xdel),
    ):
        await reprocess_dead_letters(
            fake_redis, REVISIONS_DLQ, [entry_id], session_factory=session_factory
        )

    assert order == ["Reprocessed dead letter", "xdel"]
    extra = info.call_args.kwargs["extra"]
    assert extra["entry_id"] == entry_id
    assert extra["source_id"] == "1-0"
    assert extra["fields"]["event_type"] == "source_revision_observed"


async def test_a_failed_handler_is_logged_with_its_traceback(fake_redis, session_factory):
    """``failed`` catches everything outside POISON_ERRORS, a handler bug included.
    The live loop logs that case with its stack; so must this path, or a crash
    here would be the one that leaves none."""
    entry_id = await _park(fake_redis, _parked(_observed("01J0000000000000000000000A")))
    boom = RuntimeError("handler bug")

    with (
        patch.dict(dlq_triage._REPROCESSORS, {REVISIONS_DLQ: _spy(boom, [])}),
        patch.object(dlq_triage.logger, "warning") as warning,
    ):
        await reprocess_dead_letters(
            fake_redis, REVISIONS_DLQ, [entry_id], session_factory=session_factory
        )

    [call] = warning.call_args_list
    assert call.kwargs["extra"]["outcome"] == "failed"
    assert call.kwargs["exc_info"] is boom


async def test_an_artifacts_entry_runs_through_the_artifacts_handler(fake_redis, session_factory):
    """The other queue's wiring, through its real handler: an outcome for a command
    the registry never issued is ack-and-drop, so the entry settles and goes. A
    wrong handler in _REPROCESSORS would decode the frame and not know it."""
    dlq = "content.artifacts.dlq"
    stray = ReplicationCompleteEvent(
        occurred_at=datetime(2026, 9, 24, 12, 0, tzinfo=UTC),
        command_id="never-issued",
        public_url="https://storage.googleapis.com/co-archive/archive/wa-lcb/x.html",
        info_item_rep_spec_id=str(ULID()),
        source_revision_id=str(ULID()),
        info_source_id=str(ULID()),
    )
    entry_id = (
        await fake_redis.xadd(dlq, _parked(to_wire(stray), group="archiver.artifacts"))
    ).decode()

    with patch.object(artifacts_consumer.logger, "warning") as warning:
        [result] = await reprocess_dead_letters(
            fake_redis, dlq, [entry_id], session_factory=session_factory
        )

    assert result.outcome == "reprocessed"
    assert await fake_redis.xlen(dlq) == 0
    # The artifacts handler's own verdict, not a generic settle.
    [call] = warning.call_args_list
    assert call.args[0] == "Dropping outcome for a command this registry never issued"
    assert call.kwargs["extra"]["command_id"] == "never-issued"
