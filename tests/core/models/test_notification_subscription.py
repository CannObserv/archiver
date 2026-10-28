"""NotificationSubscription model tests (archiver#363, D1).

The CHECKs hold what a hand-edit could break: the scope names exactly its ref,
``events`` is a non-empty subset of the three known events, and the channel id
is ULID-shaped. The Domain ref is ``RESTRICT`` (a Domain delete refuses while a
subscription names it); the item ref cascades, like every child of an item.
"""

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from ulid import ULID

from src.core.models import Domain, InfoItem, NotificationSubscription

CHANNEL = "01M5APS9R7A0QEDB9522MRA4CT"


async def _domain(session, name: str = "subs-model.example.com") -> Domain:
    domain = Domain(name=name)
    session.add(domain)
    await session.flush()
    return domain


async def _item(session) -> InfoItem:
    item = InfoItem(name="Subscribed")
    session.add(item)
    await session.flush()
    return item


def _sub(**kw) -> NotificationSubscription:
    fields = {
        "title": "Ops channel",
        "scope": "global",
        "events": ["change_detected"],
        "remote_channel_id": CHANNEL,
    } | kw
    return NotificationSubscription(**fields)


@pytest.mark.asyncio
async def test_global_subscription_defaults(session):
    sub = _sub()
    session.add(sub)
    await session.flush()
    await session.refresh(sub)

    assert isinstance(sub.id, ULID)
    assert sub.is_active is True
    assert sub.content_config is None
    assert sub.imported_watcher_id is None
    assert sub.domain_id is None and sub.info_item_id is None
    assert sub.created_at is not None and sub.updated_at is not None


@pytest.mark.asyncio
async def test_null_content_config_is_sql_null_not_jsonb_null(session):
    session.add(_sub())
    await session.flush()
    raw = (
        await session.execute(
            text("SELECT content_config IS NULL FROM information.notification_subscriptions")
        )
    ).scalar_one()
    assert raw is True


@pytest.mark.asyncio
async def test_each_scope_takes_exactly_its_ref(session):
    domain = await _domain(session)
    item = await _item(session)
    session.add_all(
        [
            _sub(),
            _sub(scope="domain", domain_id=domain.id),
            _sub(scope="item", info_item_id=item.info_item_id),
        ]
    )
    await session.flush()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scope, refs",
    [
        ("global", {"domain"}),
        ("global", {"item"}),
        ("domain", set()),
        ("domain", {"domain", "item"}),
        ("item", set()),
        ("item", {"domain"}),
        ("everyone", set()),
    ],
)
async def test_scope_check_refuses_a_mismatched_ref(session, scope, refs):
    domain = await _domain(session)
    item = await _item(session)
    kw = {}
    if "domain" in refs:
        kw["domain_id"] = domain.id
    if "item" in refs:
        kw["info_item_id"] = item.info_item_id
    session.add(_sub(scope=scope, **kw))
    with pytest.raises(IntegrityError, match="ck_notification_subscriptions_scope"):
        await session.flush()


@pytest.mark.asyncio
@pytest.mark.parametrize("events", [[], ["change_detected", "digest"], ["created"]])
async def test_events_check_refuses_empty_and_unknown(session, events):
    session.add(_sub(events=events))
    with pytest.raises(IntegrityError, match="ck_notification_subscriptions_events"):
        await session.flush()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "channel", ["short", "01M5APS9R7A0QEDB9522MRA4CI", "01m5aps9r7a0qedb9522mra4ct"]
)
async def test_channel_check_refuses_a_non_ulid(session, channel):
    session.add(_sub(remote_channel_id=channel))
    with pytest.raises(IntegrityError, match="ck_notification_subscriptions_channel"):
        await session.flush()


@pytest.mark.asyncio
async def test_imported_watcher_id_is_unique(session):
    watcher_id = ULID()
    session.add(_sub(imported_watcher_id=watcher_id))
    await session.flush()
    session.add(_sub(imported_watcher_id=watcher_id))
    with pytest.raises(IntegrityError, match="uq_notification_subscriptions_imported_watcher_id"):
        await session.flush()


@pytest.mark.asyncio
async def test_domain_delete_is_restricted_while_a_subscription_names_it(session):
    domain = await _domain(session)
    session.add(_sub(scope="domain", domain_id=domain.id))
    await session.flush()
    with pytest.raises(IntegrityError, match="notification_subscriptions"):
        await session.execute(delete(Domain).where(Domain.id == domain.id))


@pytest.mark.asyncio
async def test_item_delete_cascades_its_subscriptions(session):
    item = await _item(session)
    session.add(_sub(scope="item", info_item_id=item.info_item_id))
    await session.flush()

    await session.execute(delete(InfoItem).where(InfoItem.info_item_id == item.info_item_id))

    left = (await session.execute(select(NotificationSubscription))).scalars().all()
    assert left == []
