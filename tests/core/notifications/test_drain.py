"""The drain: pending rows to Notifier, oldest first (archiver#369, D4).

- A ``DispatchOut`` is terminal: ``succeeded`` → ``sent``, anything else →
  ``failed`` with Notifier's reason. Re-POSTing the key would return the same
  record, so nothing retries a delivered failure, and nothing redelivers.
- A retryable failure keeps the row ``pending`` under the same key, backed off;
  the cap ends it ``failed`` with the last reason. A refusal fails it at once.
- A row whose subscription was deleted, or is now inactive, is ``skipped``.
- Shadow rows are never claimed.
"""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select, update
from ulid import ULID

from src.core.models import NotificationDispatch, NotificationSubscription
from src.core.notifications import drain
from src.core.notifications.drain import MAX_ATTEMPTS, backoff, drain_once
from src.core.notifier.client import Dispatched, NotifierUnavailable
from tests.core.notifier.fake import FakeNotifier
from tests.core.services._dispatch_seed import DEV_SINK, seed_item, seed_subscription

pytestmark = pytest.mark.usefixtures("clean_dispatch_tables")

NOW = datetime(2026, 11, 20, 18, 0, tzinfo=UTC)


async def _queue(session_factory, sub, *, n: int = 1, **fields) -> list[ULID]:
    item = await seed_item(session_factory)
    ids = []
    async with session_factory() as session:
        for i in range(n):
            event_id = str(ULID())
            row = NotificationDispatch(
                event_id=event_id,
                event_type="watch_error",
                subscription_id=sub.id,
                info_item_id=item.info_item_id,
                remote_channel_id=DEV_SINK,
                occurred_at=NOW - timedelta(minutes=n - i),
                fact={"event_type": "watch_error"},
                title=f"title {i}",
                body=f"body {i}",
                idempotency_key=f"archiver:watch_error:{sub.id}:{event_id}",
                **({"mode": "send", "status": "pending"} | fields),
            )
            session.add(row)
            await session.flush()
            ids.append(row.id)
        await session.commit()
    return ids


async def _get(session_factory, row_id) -> NotificationDispatch:
    async with session_factory() as session:
        return await session.get(NotificationDispatch, row_id)


async def test_a_pending_row_is_sent_with_its_key(session_factory):
    sub = await seed_subscription(session_factory)
    [row_id] = await _queue(session_factory, sub)
    notifier = FakeNotifier()

    assert await drain_once(session_factory, notifier, now=NOW) == 1

    [sent] = notifier.dispatches
    row = await _get(session_factory, row_id)
    assert sent == {
        "channel_id": DEV_SINK,
        "title": "title 0",
        "body": "body 0",
        "idempotency_key": row.idempotency_key,
        "metadata": {
            "event_type": "watch_error",
            "event_id": row.event_id,
            "info_item_id": str(row.info_item_id),
            "subscription_id": str(sub.id),
            "reminder": 0,
        },
    }
    assert (row.status, row.mode) == ("sent", "send")
    assert row.notifier_dispatch_id == notifier.dispatched.id
    assert row.attempts == 1
    assert row.reason is None


async def test_rows_go_oldest_first(session_factory):
    sub = await seed_subscription(session_factory)
    await _queue(session_factory, sub, n=3)
    notifier = FakeNotifier()
    assert await drain_once(session_factory, notifier, now=NOW) == 3
    assert [d["title"] for d in notifier.dispatches] == ["title 0", "title 1", "title 2"]


async def test_a_failed_delivery_is_terminal_with_notifiers_reason(session_factory):
    sub = await seed_subscription(session_factory)
    [row_id] = await _queue(session_factory, sub)
    notifier = FakeNotifier()
    notifier.dispatched = Dispatched(id="01M5DISPATCH0000000000000B", status="failed", reason="404")

    await drain_once(session_factory, notifier, now=NOW)
    await drain_once(session_factory, notifier, now=NOW + timedelta(days=1))

    row = await _get(session_factory, row_id)
    assert (row.status, row.reason, row.notifier_dispatch_id) == (
        "failed",
        "404",
        "01M5DISPATCH0000000000000B",
    )
    assert len(notifier.dispatches) == 1


async def test_a_failed_delivery_without_a_reason_names_its_status(session_factory):
    sub = await seed_subscription(session_factory)
    [row_id] = await _queue(session_factory, sub)
    notifier = FakeNotifier()
    notifier.dispatched = Dispatched(id="01M5DISPATCH0000000000000B", status="partial")
    await drain_once(session_factory, notifier, now=NOW)
    row = await _get(session_factory, row_id)
    assert (row.status, row.reason) == ("failed", "delivery partial")


async def test_a_retryable_failure_backs_off_under_the_same_key(session_factory):
    sub = await seed_subscription(session_factory)
    [row_id] = await _queue(session_factory, sub)
    notifier = FakeNotifier(unavailable=NotifierUnavailable("transport error (ReadTimeout)"))

    await drain_once(session_factory, notifier, now=NOW)

    row = await _get(session_factory, row_id)
    assert (row.status, row.attempts, row.reason) == (
        "pending",
        1,
        "transport error (ReadTimeout)",
    )
    assert row.next_attempt_at == NOW + backoff(1)
    # Not due: untouched.
    assert await drain_once(session_factory, notifier, now=NOW + backoff(1) / 2) == 0
    # Due: the same key again.
    notifier.unavailable = None
    assert await drain_once(session_factory, notifier, now=NOW + backoff(1)) == 1
    keys = {d["idempotency_key"] for d in notifier.dispatches}
    assert keys == {row.idempotency_key}
    assert (await _get(session_factory, row_id)).status == "sent"


async def test_the_attempt_cap_ends_failed_with_the_last_reason(session_factory):
    sub = await seed_subscription(session_factory)
    [row_id] = await _queue(session_factory, sub, attempts=MAX_ATTEMPTS - 1)
    notifier = FakeNotifier(unavailable=NotifierUnavailable("unexpected HTTP 503"))

    await drain_once(session_factory, notifier, now=NOW)

    row = await _get(session_factory, row_id)
    assert (row.status, row.attempts, row.reason) == ("failed", MAX_ATTEMPTS, "unexpected HTTP 503")


async def test_a_refusal_fails_at_once(session_factory):
    sub = await seed_subscription(session_factory)
    [row_id] = await _queue(session_factory, sub)
    notifier = FakeNotifier(
        unavailable=NotifierUnavailable("Notifier has no such channel", retryable=False)
    )
    await drain_once(session_factory, notifier, now=NOW)
    row = await _get(session_factory, row_id)
    assert (row.status, row.attempts) == ("failed", 1)


async def test_a_deleted_subscriptions_row_is_skipped_not_sent(session_factory):
    sub = await seed_subscription(session_factory)
    [row_id] = await _queue(session_factory, sub)
    async with session_factory() as session:
        await session.execute(
            delete(NotificationSubscription).where(NotificationSubscription.id == sub.id)
        )
        await session.commit()
    notifier = FakeNotifier()

    assert await drain_once(session_factory, notifier, now=NOW) == 1

    row = await _get(session_factory, row_id)
    assert (row.status, row.reason) == ("skipped", "subscription deleted")
    assert notifier.dispatches == []


async def test_an_inactive_subscriptions_row_is_skipped(session_factory):
    sub = await seed_subscription(session_factory)
    [row_id] = await _queue(session_factory, sub)
    async with session_factory() as session:
        await session.execute(
            update(NotificationSubscription)
            .where(NotificationSubscription.id == sub.id)
            .values(is_active=False)
        )
        await session.commit()
    notifier = FakeNotifier()
    await drain_once(session_factory, notifier, now=NOW)
    assert (await _get(session_factory, row_id)).status == "skipped"
    assert notifier.dispatches == []


async def test_shadow_rows_are_never_claimed(session_factory):
    sub = await seed_subscription(session_factory)
    await _queue(session_factory, sub, mode="shadow", status="shadow")
    notifier = FakeNotifier()
    assert await drain_once(session_factory, notifier, now=NOW) == 0
    assert notifier.calls == []


async def test_a_locked_row_is_left_to_its_holder(session_factory):
    """``SKIP LOCKED``: a second drain never sends what the first is sending."""
    sub = await seed_subscription(session_factory)
    [row_id] = await _queue(session_factory, sub)
    notifier = FakeNotifier()
    async with session_factory() as holder:
        await holder.execute(
            select(NotificationDispatch).where(NotificationDispatch.id == row_id).with_for_update()
        )
        assert await drain_once(session_factory, notifier, now=NOW) == 0
    assert notifier.dispatches == []


def test_backoff_grows_and_is_capped():
    assert backoff(1) == timedelta(seconds=30)
    assert backoff(2) == timedelta(seconds=60)
    assert backoff(50) == drain.MAX_BACKOFF


async def test_the_loop_drains_and_stops(session_factory):
    sub = await seed_subscription(session_factory)
    [row_id] = await _queue(session_factory, sub)
    notifier = FakeNotifier()
    stop = asyncio.Event()
    task = asyncio.create_task(
        drain.run(session_factory=session_factory, notifier=notifier, stop_event=stop)
    )
    for _ in range(100):
        if notifier.dispatches:
            break
        await asyncio.sleep(0.01)
    stop.set()
    await asyncio.wait_for(task, timeout=2)
    assert (await _get(session_factory, row_id)).status == "sent"
