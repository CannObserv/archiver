"""Tests for the ``info.watch-events`` consumer (archiver#369, D2).

Group ``archiver.watch-events``, consumer ``archiver-watch-events-1``. Per fact:

1. A change, error or recovery → one row per matching subscription, acked
   after the commit; redelivered → no new row
2. An unknown or revoked ``info_item_id`` → ack, WARNING, no rows
3. ``check_rejected`` → recorded on its command, first write wins; an
   unknown ``command_id`` → ack, WARNING (archiver#370 D3)
4. A decoded payload that isn't a watch event → ack, WARNING
5. A malformed ``info_item_id`` → handler poison, ``info.watch-events.dlq``
6. A frame co-core can't decode, an unknown ``event_type`` included → DLQ as
   undecodable (version skew is reprocessed after a co-core upgrade)
7. A database failure leaves the fact pending

And: the group is created at ``0``; its name is the cluster convention's; the
cutover bound into the context decides the mode.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from co_core.pure.adapters.bus.envelope import to_wire
from co_core.pure.adapters.bus.streams import INFO_WATCH_EVENTS, group_name
from co_core.pure.models.changes import CheckRejectedEvent, SourceRevisionObservedEvent
from fakeredis import aioredis as fakeredis_aio
from sqlalchemy import select

from src.core.changes import watch_events_consumer
from src.core.changes.watch_events_consumer import CONSUMER_GROUP, DispatchContext
from src.core.models import NotificationDispatch, WatchCheckCommand
from tests.core.changes._fakeredis_xautoclaim import with_redis_cursor
from tests.core.notifications.builders import make_event
from tests.core.services._dispatch_seed import (
    seed_item,
    seed_subscription,
)

pytestmark = pytest.mark.usefixtures("clean_dispatch_tables")

DLQ = f"{INFO_WATCH_EVENTS}.dlq"


@pytest.fixture
async def fake_redis():
    r = with_redis_cursor(fakeredis_aio.FakeRedis())
    yield r
    await r.aclose()


@pytest.fixture(autouse=True)
def shadow_context():
    """Each test starts from the unbound context: shadow, no reader."""
    watch_events_consumer.bind_context(DispatchContext())
    yield
    watch_events_consumer.bind_context(DispatchContext())


async def _publish(fake_redis, fields: dict) -> None:
    await fake_redis.xadd(INFO_WATCH_EVENTS, fields)


async def _consume(fake_redis, session_factory) -> int:
    consumer = watch_events_consumer.build_consumer(fake_redis)
    await watch_events_consumer.ensure_group(consumer)
    return await watch_events_consumer.consume_once(
        session_factory=session_factory, consumer=consumer, block_ms=10
    )


async def _pending(fake_redis) -> int:
    info = await fake_redis.xpending(INFO_WATCH_EVENTS, CONSUMER_GROUP)
    return info["pending"] if isinstance(info, dict) else info[0]


async def _rows(session_factory) -> list[NotificationDispatch]:
    async with session_factory() as session:
        return list((await session.execute(select(NotificationDispatch))).scalars().all())


@pytest.mark.parametrize("event_type", ["change_detected", "watch_error", "watch_recovered"])
async def test_a_fact_is_recorded_and_acked(fake_redis, session_factory, event_type):
    item = await seed_item(session_factory)
    await seed_subscription(session_factory)
    await _publish(fake_redis, to_wire(make_event(event_type, info_item_id=str(item.info_item_id))))

    assert await _consume(fake_redis, session_factory) == 1

    assert await _pending(fake_redis) == 0
    [row] = await _rows(session_factory)
    assert (row.event_type, row.mode, row.status) == (event_type, "shadow", "shadow")


async def test_a_redelivery_records_nothing_new(fake_redis, session_factory):
    item = await seed_item(session_factory)
    await seed_subscription(session_factory)
    wire = to_wire(make_event("watch_error", info_item_id=str(item.info_item_id)))
    await _publish(fake_redis, wire)
    await _publish(fake_redis, wire)

    assert await _consume(fake_redis, session_factory) == 1
    assert await _consume(fake_redis, session_factory) == 1

    assert len(await _rows(session_factory)) == 1


async def test_the_bound_cutover_decides_the_mode(fake_redis, session_factory):
    item = await seed_item(session_factory)
    await seed_subscription(session_factory)
    event = make_event("watch_error", info_item_id=str(item.info_item_id))
    watch_events_consumer.bind_context(DispatchContext(cutover=event.occurred_at))
    await _publish(fake_redis, to_wire(event))

    await _consume(fake_redis, session_factory)

    [row] = await _rows(session_factory)
    assert (row.mode, row.status) == ("send", "pending")


async def test_an_unknown_item_is_acked_and_dropped(fake_redis, session_factory):
    await seed_subscription(session_factory)
    await _publish(
        fake_redis, to_wire(make_event("watch_error", info_item_id="01HV0000000000000000000999"))
    )

    with patch.object(watch_events_consumer.logger, "warning") as warning:
        assert await _consume(fake_redis, session_factory) == 1

    assert await _pending(fake_redis) == 0
    assert await _rows(session_factory) == []
    [call] = warning.call_args_list
    assert call.kwargs["extra"]["info_item_id"] == "01HV0000000000000000000999"


def _check_rejected(item_id: str, command_id: str, **overrides) -> CheckRejectedEvent:
    values = dict(
        occurred_at=datetime.now(UTC),
        event_id="01HV0000000000000000000004",
        info_item_id=item_id,
        info_source_id=None,
        command_id=command_id,
        reason="paused",
    )
    values.update(overrides)
    return CheckRejectedEvent(**values)


async def _seed_command(session_factory, item) -> str:
    command_id = "01HV00000000000000000C0MND"
    async with session_factory() as session:
        session.add(
            WatchCheckCommand(
                command_id=command_id,
                info_item_id=item.info_item_id,
                requested_at=datetime.now(UTC),
            )
        )
        await session.commit()
    return command_id


async def _command(session_factory, command_id: str) -> WatchCheckCommand:
    async with session_factory() as session:
        return await session.get(WatchCheckCommand, command_id)


async def test_check_rejected_closes_its_command(fake_redis, session_factory):
    """archiver#370 D3: the rejection is recorded by command_id; no notification."""
    item = await seed_item(session_factory)
    await seed_subscription(session_factory)
    command_id = await _seed_command(session_factory, item)
    await _publish(fake_redis, to_wire(_check_rejected(str(item.info_item_id), command_id)))

    with patch.object(watch_events_consumer.logger, "warning") as warning:
        assert await _consume(fake_redis, session_factory) == 1

    assert await _pending(fake_redis) == 0
    assert await _rows(session_factory) == []
    assert warning.call_args_list == []
    command = await _command(session_factory, command_id)
    assert command.rejected_reason == "paused"


async def test_a_second_rejection_for_one_command_is_a_no_op(fake_redis, session_factory):
    """A redelivered command can be pre-flighted again under a new event_id."""
    item = await seed_item(session_factory)
    command_id = await _seed_command(session_factory, item)
    await _publish(fake_redis, to_wire(_check_rejected(str(item.info_item_id), command_id)))
    await _publish(
        fake_redis,
        to_wire(
            _check_rejected(
                str(item.info_item_id),
                command_id,
                event_id="01HV0000000000000000000005",
                reason="fetch_open",
            )
        ),
    )

    with patch.object(watch_events_consumer.logger, "warning") as warning:
        assert await _consume(fake_redis, session_factory) == 1
        assert await _consume(fake_redis, session_factory) == 1

    assert await _pending(fake_redis) == 0
    assert warning.call_args_list == []
    assert (await _command(session_factory, command_id)).rejected_reason == "paused"


async def test_a_rejection_for_an_unknown_command_is_acked_with_a_warning(
    fake_redis, session_factory
):
    """Only Archiver issues commands, so an unknown one is a fault worth seeing - never a DLQ."""
    await _publish(fake_redis, to_wire(_check_rejected("01HV0000000000000000000999", "cmd-x")))

    with patch.object(watch_events_consumer.logger, "warning") as warning:
        assert await _consume(fake_redis, session_factory) == 1

    assert await _pending(fake_redis) == 0
    assert await fake_redis.xlen(DLQ) == 0
    [call] = warning.call_args_list
    assert call.kwargs["extra"]["command_id"] == "cmd-x"


async def test_a_foreign_payload_is_acked_with_a_warning(fake_redis, session_factory):
    event = SourceRevisionObservedEvent(
        occurred_at=datetime.now(UTC),
        info_source_id="01HV0000000000000000000002",
        extracted_fingerprint="sha256:" + "a" * 64,
        captured_at=datetime.now(UTC),
        content_size_bytes=1,
        content_media_type="text/plain",
        source_media_type="text/html",
        blob_uri="gs://co-gcs-blobs/x.bin",
    )
    await _publish(fake_redis, to_wire(event))

    with patch.object(watch_events_consumer.logger, "warning") as warning:
        assert await _consume(fake_redis, session_factory) == 1

    assert await _pending(fake_redis) == 0
    [call] = warning.call_args_list
    assert call.kwargs["extra"]["event_type"] == "source_revision_observed"


async def test_a_malformed_item_id_is_quarantined_as_poison(fake_redis, session_factory):
    await _publish(fake_redis, to_wire(make_event("watch_error", info_item_id="not-a-ulid")))

    assert await _consume(fake_redis, session_factory) == 1

    assert await _pending(fake_redis) == 0
    [(_, fields)] = await fake_redis.xrange(DLQ)
    assert any(b"handler poison" in v for v in fields.values())


async def test_an_unknown_event_type_is_quarantined_as_undecodable(fake_redis, session_factory):
    """Not acked: after a co-core upgrade the triage screen reprocesses it."""
    await _publish(
        fake_redis,
        {"event_type": "watch_paused", "payload": json.dumps({"event_id": "x"})},
    )

    assert await _consume(fake_redis, session_factory) == 0

    [(_, fields)] = await fake_redis.xrange(DLQ)
    assert any(b"undecodable" in v for v in fields.values())


async def test_a_database_failure_leaves_the_fact_pending(fake_redis, session_factory):
    item = await seed_item(session_factory)
    await _publish(
        fake_redis, to_wire(make_event("watch_error", info_item_id=str(item.info_item_id)))
    )

    with patch.object(
        watch_events_consumer, "record_fact", side_effect=ConnectionRefusedError("db down")
    ):
        assert await _consume(fake_redis, session_factory) == 0

    assert await _pending(fake_redis) == 1


async def test_group_is_created_at_zero(fake_redis, session_factory):
    """The two facts already on production's stream are replayed into shadow (D2)."""
    item = await seed_item(session_factory)
    await seed_subscription(session_factory)
    await _publish(
        fake_redis, to_wire(make_event("watch_error", info_item_id=str(item.info_item_id)))
    )

    assert await _consume(fake_redis, session_factory) == 1


def test_consumer_group_conforms_to_the_cluster_convention() -> None:
    """Derived, not spelled (cannobserv#384); the literal is the load-bearing half."""
    assert CONSUMER_GROUP == group_name(INFO_WATCH_EVENTS, "archiver")
    assert CONSUMER_GROUP == "archiver.watch-events"


def test_the_consumer_names_itself_from_its_group(fake_redis) -> None:
    assert watch_events_consumer.build_consumer(fake_redis).name == "archiver-watch-events-1"
