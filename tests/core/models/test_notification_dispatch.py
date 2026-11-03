"""NotificationDispatch model tests (archiver#369, D1).

One row per (fact, matching subscription), plus one per error reminder: the
shadow log and the dispatch outbox in one table. The CHECKs hold what a
hand-edit could break: a shadow row is never pending, only ``watch_error``
carries reminders, and a reminder carries its own instant. The subscription ref
is ``SET NULL``: deleting a subscription keeps the history, and its pending rows
are skipped, never sent.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from ulid import ULID

from src.core.models import NotificationDispatch, NotificationSubscription

CHANNEL = "01M5APS9R7A0QEDB9522MRA4CT"
EVENT_ID = "01HV0000000000000000000003"
OCCURRED_AT = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


async def _sub(session) -> NotificationSubscription:
    sub = NotificationSubscription(
        title="Ops", scope="global", events=["watch_error"], remote_channel_id=CHANNEL
    )
    session.add(sub)
    await session.flush()
    return sub


def _row(sub: NotificationSubscription | None, **kw) -> NotificationDispatch:
    fields = {
        "event_id": EVENT_ID,
        "event_type": "watch_error",
        "subscription_id": sub.id if sub is not None else None,
        "info_item_id": ULID(),
        "remote_channel_id": CHANNEL,
        "occurred_at": OCCURRED_AT,
        "fact": {"event_type": "watch_error"},
        "title": "t",
        "body": "b",
        "mode": "shadow",
        "status": "shadow",
        "idempotency_key": f"archiver:watch_error:{sub.id if sub else 'x'}:{EVENT_ID}",
    } | kw
    return NotificationDispatch(**fields)


async def _flush_fails(session, row) -> None:
    session.add(row)
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            await session.flush()


@pytest.mark.asyncio
async def test_defaults(session):
    row = _row(await _sub(session))
    session.add(row)
    await session.flush()
    await session.refresh(row)
    assert isinstance(row.id, ULID)
    assert row.reminder == 0
    assert row.attempts == 0
    assert row.reminded_at is None and row.next_attempt_at is None
    assert row.created_at is not None


@pytest.mark.asyncio
async def test_one_row_per_fact_subscription_and_reminder(session):
    sub = await _sub(session)
    session.add(_row(sub))
    await session.flush()
    await _flush_fails(session, _row(sub, idempotency_key="other"))


@pytest.mark.asyncio
async def test_the_idempotency_key_is_unique(session):
    sub = await _sub(session)
    session.add(_row(sub))
    await session.flush()
    await _flush_fails(session, _row(sub, event_id="01HV0000000000000000000009"))


@pytest.mark.asyncio
async def test_a_reminder_shares_its_episode_event_id(session):
    sub = await _sub(session)
    session.add_all(
        [
            _row(sub),
            _row(
                sub,
                reminder=1,
                reminded_at=OCCURRED_AT,
                idempotency_key=f"archiver:watch_error_reminder:{sub.id}:{EVENT_ID}:1",
            ),
        ]
    )
    await session.flush()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fields",
    [
        {"mode": "shadow", "status": "pending"},
        {"mode": "send", "status": "shadow"},
        {"mode": "loud", "status": "pending"},
        {"status": "queued", "mode": "send"},
        {"event_type": "check_rejected"},
        {"event_type": "change_detected", "reminder": 1, "reminded_at": OCCURRED_AT},
        {"reminder": 1},
        {"reminded_at": OCCURRED_AT},
        {"reminder": -1},
    ],
)
async def test_checks_refuse(session, fields):
    await _flush_fails(session, _row(await _sub(session), **fields))


@pytest.mark.asyncio
async def test_deleting_a_subscription_keeps_its_rows(session):
    sub = await _sub(session)
    row = _row(sub, mode="send", status="pending")
    session.add(row)
    await session.flush()
    await session.execute(
        delete(NotificationSubscription).where(NotificationSubscription.id == sub.id)
    )
    await session.flush()
    await session.refresh(row)
    assert row.subscription_id is None
    assert row.status == "pending"
