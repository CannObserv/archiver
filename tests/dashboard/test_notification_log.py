"""The dispatch log, ``/dashboard/notifications/log`` (archiver#369, D6).

F3's parity evidence: every composed row, newest first, filterable by mode,
status, event and item. A filter the page doesn't know is ignored, never a 422
(the dashboard clamps). It reads only: no Notifier call, no write.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from ulid import ULID

from src.api.deps import get_notifier
from src.api.main import app
from src.core.models import InfoItem, NotificationDispatch, NotificationSubscription
from tests.core.notifier.fake import FakeNotifier

_HEADERS = {"X-ExeDev-UserID": "ext-log", "X-ExeDev-Email": "log@example.com"}
CHANNEL = "01M5APS9R7A0QEDB9522MRA4CT"
AT = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
LOG = "/dashboard/notifications/log"


async def _seed(session):
    item = InfoItem(name="Logged item")
    other = InfoItem(name="Other item")
    sub = NotificationSubscription(
        title="Ops channel", scope="global", events=["watch_error"], remote_channel_id=CHANNEL
    )
    session.add_all([item, other, sub])
    await session.flush()
    rows = []
    for i, (event, mode, status, target, extra) in enumerate(
        [
            ("change_detected", "shadow", "shadow", item, {}),
            (
                "watch_error",
                "send",
                "sent",
                item,
                {"notifier_dispatch_id": "01M5DISPATCH0000000000000A"},
            ),
            ("watch_error", "send", "failed", other, {"reason": "slack: 404"}),
            ("watch_error", "shadow", "shadow", item, {"reminder": 1, "reminded_at": AT}),
        ]
    ):
        event_id = str(ULID())
        row = NotificationDispatch(
            event_id=event_id,
            event_type=event,
            subscription_id=sub.id,
            info_item_id=target.info_item_id,
            remote_channel_id=CHANNEL,
            occurred_at=AT,
            fact={"event_type": event},
            title=f"title {i} <b>",
            body=f"body {i}",
            mode=mode,
            status=status,
            idempotency_key=event_id,
            created_at=AT + timedelta(minutes=i),
            **extra,
        )
        session.add(row)
        rows.append(row)
    await session.flush()
    return item, other, sub, rows


def _titles(text: str) -> list[str]:
    return [t for t in (f"title {i} &lt;b&gt;" for i in range(4)) if t in text]


@pytest.mark.asyncio
async def test_every_row_newest_first(client, session):
    item, _, sub, rows = await _seed(session)

    r = await client.get(LOG, headers=_HEADERS)

    assert r.status_code == 200
    text = r.text
    order = [text.index(f"title {i} &lt;b&gt;") for i in (3, 2, 1, 0)]
    assert order == sorted(order)
    assert f'href="/dashboard/info-items/{item.info_item_id}"' in text
    assert f'href="/dashboard/notifications/{sub.id}/edit"' in text
    assert "01M5DISPATCH0000000000000A" in text
    assert "slack: 404" in text
    assert "reminder 1" in text
    assert "4 rows" in text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("mode=send", [1, 2]),
        ("mode=shadow", [0, 3]),
        ("status=failed", [2]),
        ("event=change_detected", [0]),
        ("event=watch_error&mode=shadow", [3]),
    ],
)
async def test_filters(client, session, query, expected):
    await _seed(session)
    r = await client.get(f"{LOG}?{query}", headers=_HEADERS)
    assert r.status_code == 200
    assert _titles(r.text) == [f"title {i} &lt;b&gt;" for i in expected]


@pytest.mark.asyncio
async def test_the_item_filter(client, session):
    _, other, _, _ = await _seed(session)
    r = await client.get(f"{LOG}?item={other.info_item_id}", headers=_HEADERS)
    assert _titles(r.text) == ["title 2 &lt;b&gt;"]


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["mode=loud", "status=queued", "event=check_rejected", "item=x"])
async def test_an_unknown_filter_is_ignored_not_refused(client, session, query):
    await _seed(session)
    r = await client.get(f"{LOG}?{query}", headers=_HEADERS)
    assert r.status_code == 200
    assert len(_titles(r.text)) == 4


@pytest.mark.asyncio
async def test_a_deleted_subscription_reads_as_deleted(client, session):
    _, _, sub, rows = await _seed(session)
    await session.delete(sub)
    await session.flush()
    for row in rows:
        await session.refresh(row)
    r = await client.get(LOG, headers=_HEADERS)
    assert "deleted" in r.text


@pytest.mark.asyncio
async def test_pagination_clamps(client, session):
    await _seed(session)
    r = await client.get(f"{LOG}?limit=2&offset=-5", headers=_HEADERS)
    assert r.status_code == 200
    assert _titles(r.text) == ["title 2 &lt;b&gt;", "title 3 &lt;b&gt;"]
    assert "offset=2" in r.text


@pytest.mark.asyncio
async def test_it_reads_only(client, session):
    await _seed(session)
    notifier = FakeNotifier()
    app.dependency_overrides[get_notifier] = lambda: notifier
    before = await session.scalar(select(func.count()).select_from(NotificationDispatch))
    r = await client.get(LOG, headers=_HEADERS)
    assert r.status_code == 200
    assert notifier.calls == []
    assert await session.scalar(select(func.count()).select_from(NotificationDispatch)) == before


@pytest.mark.asyncio
async def test_the_list_page_links_the_log(client):
    r = await client.get("/dashboard/notifications/", headers=_HEADERS)
    assert f'href="{LOG}"' in r.text
