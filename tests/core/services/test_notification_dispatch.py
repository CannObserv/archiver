"""``record_fact``: compose a fact per subscription and record it (archiver#369, D1-D3).

One row per (fact, matching subscription). Shadow unless T is set and the fact
occurred at or after it. A redelivered fact composes nothing and inserts
nothing. An archived, paused or host-suspended item still gets its fact (D2).
"""

import logging
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select

from src.core.models import NotificationDispatch, NotificationSubscription
from src.core.notifications.diff_loader import TextReader
from src.core.services.notification_dispatch import (
    InvalidFactError,
    PlannedRow,
    UnknownInfoItemError,
    idempotency_key,
    insert_rows,
    record_fact,
    reminder_key,
)
from tests.core.notifications.builders import FakeStorage, make_event, uri
from tests.core.services._dispatch_seed import (
    DEV_SINK,
    OTHER_CHANNEL,
    seed_item,
    seed_subscription,
)

pytestmark = pytest.mark.usefixtures("clean_dispatch_tables")

OLD, NEW = b"alpha beta gamma\n", b"alpha delta gamma\n"
T = datetime(2026, 4, 14, 12, 0, tzinfo=UTC)


def _change(item, **fields):
    return make_event(
        "change_detected",
        info_item_id=str(item.info_item_id),
        previous_fingerprint=f"sha256:{uri(OLD).rsplit('/', 1)[1].removesuffix('.bin')}",
        current_fingerprint=f"sha256:{uri(NEW).rsplit('/', 1)[1].removesuffix('.bin')}",
        previous_text_uri=uri(OLD),
        current_text_uri=uri(NEW),
        **fields,
    )


def _reader(storage: FakeStorage) -> TextReader:
    return TextReader(storage, "co-gcs-processor")


async def _rows(session_factory) -> list[NotificationDispatch]:
    async with session_factory() as session:
        return list(
            (
                await session.execute(
                    select(NotificationDispatch).order_by(NotificationDispatch.subscription_id)
                )
            )
            .scalars()
            .all()
        )


async def test_a_change_is_recorded_once_per_subscription_in_shadow(session_factory):
    item = await seed_item(session_factory)
    a = await seed_subscription(session_factory, title="A")
    b = await seed_subscription(session_factory, title="B", remote_channel_id=OTHER_CHANNEL)
    event = _change(item)
    storage = FakeStorage(OLD, NEW)

    inserted = await record_fact(session_factory, event, text_reader=_reader(storage), cutover=None)

    assert inserted == 2
    rows = await _rows(session_factory)
    assert [(r.subscription_id, r.remote_channel_id) for r in rows] == [
        (a.id, DEV_SINK),
        (b.id, OTHER_CHANNEL),
    ]
    for row, sub in zip(rows, (a, b), strict=True):
        assert row.mode == row.status == "shadow"
        assert row.event_id == event.event_id
        assert row.event_type == "change_detected"
        assert row.reminder == 0 and row.reminded_at is None
        assert row.info_item_id == item.info_item_id
        assert row.occurred_at == event.occurred_at
        assert row.idempotency_key == f"archiver:change_detected:{sub.id}:{event.event_id}"
        assert row.fact == event.model_dump(mode="json")
        assert row.title == "[Watcher] Change: Licensing page"
        assert "+ delta" in row.body
    # One diff for the fact, not one per subscription.
    assert len(storage.gets) == 2


@pytest.mark.parametrize(
    ("occurred_at", "cutover", "mode", "status"),
    [
        (T, T, "send", "pending"),
        (T + timedelta(seconds=1), T, "send", "pending"),
        (T - timedelta(microseconds=1), T, "shadow", "shadow"),
        (T, None, "shadow", "shadow"),
    ],
)
async def test_the_cutover_decides_the_mode(session_factory, occurred_at, cutover, mode, status):
    item = await seed_item(session_factory)
    await seed_subscription(session_factory)
    event = make_event("watch_error", info_item_id=str(item.info_item_id), occurred_at=occurred_at)

    await record_fact(session_factory, event, text_reader=None, cutover=cutover)

    [row] = await _rows(session_factory)
    assert (row.mode, row.status) == (mode, status)


async def test_a_redelivered_fact_composes_and_inserts_nothing(session_factory):
    item = await seed_item(session_factory)
    await seed_subscription(session_factory)
    event = _change(item)
    storage = FakeStorage(OLD, NEW)
    await record_fact(session_factory, event, text_reader=_reader(storage), cutover=None)
    reads = len(storage.gets)

    assert (
        await record_fact(session_factory, event, text_reader=_reader(storage), cutover=None) == 0
    )
    assert len(storage.gets) == reads
    assert len(await _rows(session_factory)) == 1


async def test_no_diff_is_read_when_no_row_shows_one(session_factory):
    item = await seed_item(session_factory)
    await seed_subscription(
        session_factory, content_config={"default": {"include_diff_snippet": False}}
    )
    storage = FakeStorage(OLD, NEW)
    await record_fact(session_factory, _change(item), text_reader=_reader(storage), cutover=None)
    assert storage.gets == []


async def test_an_unreadable_diff_still_records_with_its_reason(session_factory):
    item = await seed_item(session_factory)
    await seed_subscription(session_factory)
    await record_fact(session_factory, _change(item), text_reader=None, cutover=None)
    [row] = await _rows(session_factory)
    assert "DIFF: unavailable (previous text unreadable)" in row.body


async def test_only_subscriptions_that_hear_the_event_get_rows(session_factory):
    item = await seed_item(session_factory)
    other = await seed_item(session_factory, name="Other")
    hears = await seed_subscription(session_factory, events=["watch_error"])
    await seed_subscription(session_factory, events=["change_detected"])
    await seed_subscription(session_factory, is_active=False)
    await seed_subscription(session_factory, scope="item", info_item_id=other.info_item_id)
    event = make_event("watch_error", info_item_id=str(item.info_item_id))

    assert await record_fact(session_factory, event, text_reader=None, cutover=None) == 1
    [row] = await _rows(session_factory)
    assert row.subscription_id == hears.id


async def test_no_subscription_records_nothing(session_factory):
    item = await seed_item(session_factory)
    event = make_event("watch_recovered", info_item_id=str(item.info_item_id))
    assert await record_fact(session_factory, event, text_reader=None, cutover=None) == 0


@pytest.mark.parametrize(
    "state",
    [{"archived_at": T}, {"watch_active": False}],
)
async def test_an_archived_or_paused_item_still_gets_its_fact(session_factory, state):
    """D2: the fact happened before the state changed; Watcher would have sent it."""
    item = await seed_item(session_factory, **state)
    await seed_subscription(session_factory)
    event = make_event("watch_error", info_item_id=str(item.info_item_id))
    assert await record_fact(session_factory, event, text_reader=None, cutover=None) == 1


async def test_an_unknown_item_raises(session_factory):
    await seed_subscription(session_factory)
    event = make_event("watch_error", info_item_id="01HV0000000000000000000999")
    with pytest.raises(UnknownInfoItemError):
        await record_fact(session_factory, event, text_reader=None, cutover=None)
    assert await _rows(session_factory) == []


async def test_a_malformed_item_id_is_poison(session_factory):
    event = make_event("watch_error", info_item_id="not-a-ulid")
    with pytest.raises(InvalidFactError):
        await record_fact(session_factory, event, text_reader=None, cutover=None)


async def test_a_subscription_deleted_before_the_insert_gets_no_row(session_factory):
    item = await seed_item(session_factory)
    kept = await seed_subscription(session_factory)
    gone = await seed_subscription(session_factory)
    event = make_event("watch_error", info_item_id=str(item.info_item_id))
    async with session_factory() as session:
        await session.execute(
            delete(NotificationSubscription).where(NotificationSubscription.id == gone.id)
        )
        await session.commit()

    rows = [
        PlannedRow(
            subscription_id=sub.id,
            remote_channel_id=DEV_SINK,
            title="t",
            body="b",
            idempotency_key=idempotency_key("watch_error", sub.id, event.event_id),
        )
        for sub in (kept, gone)
    ]
    async with session_factory() as session:
        assert await insert_rows(session, event, rows, mode="shadow") == 1
        await session.commit()
    [row] = await _rows(session_factory)
    assert row.subscription_id == kept.id


async def test_a_custom_template_renders_and_a_broken_one_falls_back(session_factory):
    item = await seed_item(session_factory)
    custom = await seed_subscription(
        session_factory, content_config={"default": {"title_template": "{{ item_name }} broke"}}
    )
    broken = await seed_subscription(
        session_factory,
        content_config={"default": {"title_template": "{% for i in range(5000) %}{% endfor %}"}},
    )
    event = make_event("watch_error", info_item_id=str(item.info_item_id))
    await record_fact(session_factory, event, text_reader=None, cutover=None)
    titles = {r.subscription_id: r.title for r in await _rows(session_factory)}
    assert titles[custom.id] == "Licensing page broke"
    assert titles[broken.id] == "[Watcher] Error: Licensing page"


def test_the_keys():
    assert idempotency_key("watch_error", "S", "E") == "archiver:watch_error:S:E"
    assert reminder_key("S", "E", 2) == "archiver:watch_error_reminder:S:E:2"


async def test_an_invalid_stored_config_falls_back_without_stalling_the_fact(
    session_factory, caplog
):
    """CR 1: a stored ``content_config`` today's validator refuses (the drift
    ``audit_stored_documents`` sweeps for) must not stall every other row."""
    item = await seed_item(session_factory)
    good = await seed_subscription(session_factory)
    async with session_factory() as session:
        bad = NotificationSubscription(
            title="Drifted",
            scope="global",
            events=["watch_error"],
            remote_channel_id=DEV_SINK,
            content_config={"default": {"include_diff_snipet": True}},
        )
        session.add(bad)
        await session.commit()
    event = make_event("watch_error", info_item_id=str(item.info_item_id))

    with caplog.at_level(logging.WARNING):
        assert await record_fact(session_factory, event, text_reader=None, cutover=None) == 2

    titles = {r.subscription_id: r.title for r in await _rows(session_factory)}
    assert titles[good.id] == titles[bad.id] == "[Watcher] Error: Licensing page"
    [record] = [r for r in caplog.records if "stored content options" in r.getMessage()]
    assert record.subscription_id == str(bad.id)
    assert "include_diff_snipet" not in caplog.text
