"""Error reminders and retention (archiver#369, D5 and D1).

Per (subscription, item in error): when the subscription's newest row for the
open episode, the edge or its last reminder, is at least the interval old, a
reminder row goes in, composed with ``previously_notified_at``. The state is the
rows themselves. Only an item Watcher still checks is reminded: in error, not
archived, not paused, and its host not suspended.
"""

import logging
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update
from ulid import ULID

from src.core.models import Domain, NotificationDispatch, NotificationSubscription
from src.core.notifications.reminders import (
    DEFAULT_RENOTIFY_INTERVAL,
    DEFAULT_RETENTION_DAYS,
    prune_dispatches,
    remind_once,
    resolve_renotify_interval,
    resolve_retention_days,
)
from src.core.services.notification_dispatch import record_fact
from tests.core.notifications.builders import make_event
from tests.core.services._dispatch_seed import (
    seed_item,
    seed_subscription,
    seed_watch_status,
)

pytestmark = pytest.mark.usefixtures("clean_dispatch_tables")

EDGE_AT = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
DAY = timedelta(hours=24)


async def _episode(session_factory, *, health="error", subs=1, item_fields=None, **event):
    """An item in error whose edge was recorded for ``subs`` global subscriptions."""
    item = await seed_item(session_factory, **(item_fields or {}))
    created = [await seed_subscription(session_factory) for _ in range(subs)]
    await seed_watch_status(session_factory, item, health)
    edge = make_event(
        "watch_error",
        info_item_id=str(item.info_item_id),
        event_id=str(ULID()),
        occurred_at=EDGE_AT,
        status_code=503,
        **event,
    )
    await record_fact(session_factory, edge, text_reader=None, cutover=None)
    return item, created, edge


async def _reminders(session_factory) -> list[NotificationDispatch]:
    async with session_factory() as session:
        return list(
            (
                await session.execute(
                    select(NotificationDispatch)
                    .where(NotificationDispatch.reminder > 0)
                    .order_by(NotificationDispatch.reminder)
                )
            )
            .scalars()
            .all()
        )


async def _remind(session_factory, now, *, cutover=None) -> int:
    return await remind_once(
        session_factory, now=now, cutover=cutover, interval=DEFAULT_RENOTIFY_INTERVAL
    )


async def test_a_due_episode_is_reminded(session_factory):
    item, [sub], edge = await _episode(session_factory)

    assert await _remind(session_factory, EDGE_AT + DAY) == 1

    [row] = await _reminders(session_factory)
    assert row.reminder == 1
    assert row.event_id == edge.event_id
    assert row.event_type == "watch_error"
    assert row.subscription_id == sub.id
    assert row.occurred_at == EDGE_AT
    assert row.reminded_at == EDGE_AT + DAY
    assert row.idempotency_key == f"archiver:watch_error_reminder:{sub.id}:{edge.event_id}:1"
    assert (row.mode, row.status) == ("shadow", "shadow")
    assert row.fact == edge.model_dump(mode="json")
    assert "returned HTTP 503" in row.body
    assert "Still failing — previously notified 2026-11-01T12:00:00" in row.body


async def test_an_episode_not_yet_due_is_left(session_factory):
    await _episode(session_factory)
    assert await _remind(session_factory, EDGE_AT + DAY - timedelta(seconds=1)) == 0


async def test_the_next_reminder_is_timed_from_the_last(session_factory):
    _, [sub], edge = await _episode(session_factory)
    await _remind(session_factory, EDGE_AT + DAY + timedelta(hours=1))

    assert await _remind(session_factory, EDGE_AT + 2 * DAY) == 0
    assert await _remind(session_factory, EDGE_AT + 2 * DAY + timedelta(hours=1)) == 1

    second = (await _reminders(session_factory))[1]
    assert second.reminder == 2
    assert second.idempotency_key.endswith(f"{edge.event_id}:2")
    assert "previously notified 2026-11-02T13:00:00" in second.body


async def test_a_tick_twice_at_one_instant_reminds_once(session_factory):
    await _episode(session_factory)
    await _remind(session_factory, EDGE_AT + DAY)
    assert await _remind(session_factory, EDGE_AT + DAY) == 0
    assert len(await _reminders(session_factory)) == 1


async def test_each_subscription_is_reminded(session_factory):
    await _episode(session_factory, subs=2)
    assert await _remind(session_factory, EDGE_AT + DAY) == 2


async def test_a_recovery_closes_the_episode(session_factory):
    item, _, _ = await _episode(session_factory)
    recovered = make_event(
        "watch_recovered",
        info_item_id=str(item.info_item_id),
        event_id=str(ULID()),
        occurred_at=EDGE_AT + timedelta(hours=1),
    )
    await record_fact(session_factory, recovered, text_reader=None, cutover=None)
    assert await _remind(session_factory, EDGE_AT + DAY) == 0


async def test_a_newer_error_edge_supersedes_the_episode(session_factory):
    item, [sub], _ = await _episode(session_factory)
    newer = make_event(
        "watch_error",
        info_item_id=str(item.info_item_id),
        event_id=str(ULID()),
        occurred_at=EDGE_AT + timedelta(hours=12),
    )
    await record_fact(session_factory, newer, text_reader=None, cutover=None)

    assert await _remind(session_factory, EDGE_AT + DAY) == 0
    assert await _remind(session_factory, EDGE_AT + DAY + timedelta(hours=12)) == 1
    [row] = await _reminders(session_factory)
    assert row.event_id == newer.event_id


@pytest.mark.parametrize("health", ["ok", "unknown", None])
async def test_an_item_not_in_error_is_not_reminded(session_factory, health):
    await _episode(session_factory, health=health)
    assert await _remind(session_factory, EDGE_AT + DAY) == 0


@pytest.mark.parametrize("item_fields", [{"archived_at": EDGE_AT}, {"watch_active": False}])
async def test_an_archived_or_paused_item_is_not_reminded(session_factory, item_fields):
    """Watcher doesn't check it, so Watcher couldn't remind it either."""
    await _episode(session_factory, item_fields=item_fields)
    assert await _remind(session_factory, EDGE_AT + DAY) == 0


@pytest.mark.parametrize("domain_fields", [{"is_active": False}, {"archived_at": EDGE_AT}])
async def test_an_item_on_a_suspended_host_is_not_reminded(session_factory, domain_fields):
    await _episode(session_factory)
    async with session_factory() as session:
        await session.execute(update(Domain).values(**domain_fields))
        await session.commit()
    assert await _remind(session_factory, EDGE_AT + DAY) == 0


async def test_an_item_paused_after_null_is_still_reminded(session_factory):
    """``watch_active`` NULL is "no opinion": Watcher keeps checking it."""
    await _episode(session_factory, item_fields={"watch_active": None})
    assert await _remind(session_factory, EDGE_AT + DAY) == 1


async def test_an_error_with_no_episode_row_is_skipped_and_said(session_factory, caplog):
    item = await seed_item(session_factory)
    await seed_subscription(session_factory)
    await seed_watch_status(session_factory, item, "error")
    with caplog.at_level(logging.INFO):
        assert await _remind(session_factory, EDGE_AT + DAY) == 0
    [record] = [r for r in caplog.records if "no episode" in r.getMessage()]
    assert record.info_item_id == str(item.info_item_id)


async def test_a_subscription_that_never_heard_the_episode_is_not_reminded(session_factory):
    await _episode(session_factory)
    await seed_subscription(session_factory)  # created mid-episode
    assert await _remind(session_factory, EDGE_AT + DAY) == 1


async def test_an_inactive_or_deaf_subscription_is_not_reminded(session_factory):
    _, [sub], _ = await _episode(session_factory)
    async with session_factory() as session:
        await session.execute(
            update(NotificationSubscription)
            .where(NotificationSubscription.id == sub.id)
            .values(events=["change_detected"])
        )
        await session.commit()
    assert await _remind(session_factory, EDGE_AT + DAY) == 0


async def test_the_mode_is_the_reminders_own_instant(session_factory):
    """D3 by the reminder's instant: a shadow edge's reminder after T sends."""
    await _episode(session_factory)
    now = EDGE_AT + DAY
    await _remind(session_factory, now, cutover=now)
    [row] = await _reminders(session_factory)
    assert (row.mode, row.status) == ("send", "pending")


# --- knobs ---


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, timedelta(hours=24)),
        ("6h", timedelta(hours=6)),
        ("30m", timedelta(minutes=30)),
        ("2d", timedelta(days=2)),
        (" 45s ", timedelta(seconds=45)),
        ("0s", timedelta(0)),
    ],
)
def test_the_interval_is_read(raw, expected):
    assert resolve_renotify_interval(raw) == expected


@pytest.mark.parametrize("raw", ["", "24", "1w", "soon", "-1h"])
def test_a_malformed_interval_falls_back_and_warns(raw, caplog):
    with caplog.at_level(logging.WARNING):
        assert resolve_renotify_interval(raw) == DEFAULT_RENOTIFY_INTERVAL
    assert caplog.records


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(None, DEFAULT_RETENTION_DAYS), ("30", 30), ("0", None), ("-1", None), ("x", 90)],
)
def test_the_retention_is_read(raw, expected):
    assert resolve_retention_days(raw) == expected


# --- retention ---


async def test_retention_prunes_old_terminal_rows_and_keeps_pending(session_factory):
    item, [sub], _ = await _episode(session_factory)
    async with session_factory() as session:
        for status, mode in (("sent", "send"), ("pending", "send"), ("failed", "send")):
            event_id = str(ULID())
            session.add(
                NotificationDispatch(
                    event_id=event_id,
                    event_type="change_detected",
                    subscription_id=sub.id,
                    info_item_id=item.info_item_id,
                    remote_channel_id=sub.remote_channel_id,
                    occurred_at=EDGE_AT,
                    fact={},
                    title="t",
                    body="b",
                    mode=mode,
                    status=status,
                    idempotency_key=event_id,
                )
            )
        await session.commit()

    assert await prune_dispatches(session_factory, retention_days=90, now=datetime.now(UTC)) == 0
    pruned = await prune_dispatches(
        session_factory, retention_days=90, now=datetime.now(UTC) + timedelta(days=91)
    )

    assert pruned == 3  # the shadow edge, sent and failed
    async with session_factory() as session:
        left = (await session.execute(select(NotificationDispatch.status))).scalars().all()
    assert left == ["pending"]


async def test_retention_off_prunes_nothing(session_factory):
    await _episode(session_factory)
    assert await prune_dispatches(session_factory, retention_days=None, now=EDGE_AT) == 0
