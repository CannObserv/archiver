"""Who hears: ``subscriptions_for`` and the subscription writes (archiver#363, D2).

Watcher's matching: an event goes to every **active** subscription whose
``events`` hold it and whose scope matches the item - global, the item's host's
Domain, or the item itself. The scopes are a union: nothing overrides or opts
out, and two subscriptions on one channel both match (watcher #200 F2).

The host is the **announcing** source's (the active binding's)
``InfoSource.domain_name``, matched to a Domain row by ``name``: no field on the
item. So a binding that moves host moves the item's domain subscriptions, and
an item with no active binding, or a host with no Domain row, hears only global
and item scope. Archive, pause and host suspension filter nothing: Watcher
checks none of those items, so no event arrives (#369 decides an in-flight one).
"""

import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker
from ulid import ULID

from src.core.models import Domain, InfoItem, InfoItemSource, InfoSource, NotificationSubscription
from src.core.services import domain_policy
from src.core.services import notification_subscriptions as subs

CHANNEL = "01M5APS9R7A0QEDB9522MRA4CT"
OTHER_CHANNEL = "01M5APS9R7A0QEDB9522MRA4CV"
_SPECS = [{"schema_version": 1, "extraction": {"algorithm": "css", "selector": "body"}}]


async def _domain(session, name: str) -> Domain:
    domain = Domain(name=name)
    session.add(domain)
    await session.flush()
    return domain


async def _bind(session, item: InfoItem, host: str) -> InfoItemSource:
    source = InfoSource(url=f"https://{host}/{ULID()}", source_specs=_SPECS, domain_name=host)
    session.add(source)
    await session.flush()
    binding = InfoItemSource(info_item_id=item.info_item_id, info_source_id=source.info_source_id)
    session.add(binding)
    await session.flush()
    return binding


async def _item(session, host: str | None = None) -> InfoItem:
    item = InfoItem(name=f"on {host}")
    session.add(item)
    await session.flush()
    if host is not None:
        await _bind(session, item, host)
    return item


async def _sub(session, scope: str = "global", **kw) -> NotificationSubscription:
    fields = {
        "title": f"{scope} sub",
        "scope": scope,
        "events": ["change_detected", "watch_error", "watch_recovered"],
        "remote_channel_id": CHANNEL,
    } | kw
    sub = NotificationSubscription(**fields)
    session.add(sub)
    await session.flush()
    return sub


async def _ids(session, item: InfoItem, event: str = "change_detected") -> list[ULID]:
    return [s.id for s in await subs.subscriptions_for(session, item.info_item_id, event)]


@pytest.mark.asyncio
async def test_the_union_of_global_domain_and_item_scope_each_once_in_id_order(session):
    domain = await _domain(session, "union.example.com")
    item = await _item(session, "union.example.com")
    a = await _sub(session)
    b = await _sub(session, "domain", domain_id=domain.id)
    c = await _sub(session, "item", info_item_id=item.info_item_id)

    assert await _ids(session, item) == sorted([a.id, b.id, c.id])


@pytest.mark.asyncio
async def test_two_subscriptions_on_one_channel_both_match(session):
    item = await _item(session, "dup.example.com")
    first = await _sub(session)
    second = await _sub(session)

    assert await _ids(session, item) == sorted([first.id, second.id])


@pytest.mark.asyncio
async def test_inactive_subscriptions_and_other_events_do_not_match(session):
    item = await _item(session, "filter.example.com")
    await _sub(session, is_active=False)
    errors_only = await _sub(session, events=["watch_error"])

    assert await _ids(session, item, "change_detected") == []
    assert await _ids(session, item, "watch_error") == [errors_only.id]


@pytest.mark.asyncio
async def test_other_items_and_other_domains_do_not_match(session):
    mine = await _domain(session, "mine.example.com")
    theirs = await _domain(session, "theirs.example.com")
    item = await _item(session, "mine.example.com")
    other = await _item(session, "theirs.example.com")
    await _sub(session, "domain", domain_id=theirs.id)
    await _sub(session, "item", info_item_id=other.info_item_id)
    hit = await _sub(session, "domain", domain_id=mine.id)

    assert await _ids(session, item) == [hit.id]


@pytest.mark.asyncio
async def test_a_binding_that_moves_host_moves_the_domain_subscriptions(session):
    old = await _domain(session, "old-host.example.com")
    new = await _domain(session, "new-host.example.com")
    item = await _item(session)
    binding = await _bind(session, item, "old-host.example.com")
    on_old = await _sub(session, "domain", domain_id=old.id)
    on_new = await _sub(session, "domain", domain_id=new.id)
    assert await _ids(session, item) == [on_old.id]

    binding.deactivated_at = datetime.now(UTC)
    await session.flush()
    await _bind(session, item, "new-host.example.com")

    assert await _ids(session, item) == [on_new.id]


@pytest.mark.asyncio
async def test_an_item_with_no_active_binding_hears_only_global_and_item_scope(session):
    domain = await _domain(session, "unbound.example.com")
    item = await _item(session)
    binding = await _bind(session, item, "unbound.example.com")
    binding.deactivated_at = datetime.now(UTC)
    await session.flush()
    g = await _sub(session)
    await _sub(session, "domain", domain_id=domain.id)
    i = await _sub(session, "item", info_item_id=item.info_item_id)

    assert await _ids(session, item) == sorted([g.id, i.id])


@pytest.mark.asyncio
async def test_a_host_with_no_domain_row_hears_only_global_and_item_scope(session):
    other = await _domain(session, "rowed.example.com")
    item = await _item(session, "rowless.example.com")
    g = await _sub(session)
    await _sub(session, "domain", domain_id=other.id)
    i = await _sub(session, "item", info_item_id=item.info_item_id)

    assert await _ids(session, item) == sorted([g.id, i.id])


@pytest.mark.asyncio
async def test_archived_items_and_suspended_hosts_are_not_filtered(session):
    domain = await _domain(session, "quiet.example.com")
    domain.is_active = False
    domain.archived_at = datetime.now(UTC)
    item = await _item(session, "quiet.example.com")
    item.archived_at = datetime.now(UTC)
    item.watch_active = False
    await session.flush()
    on_domain = await _sub(session, "domain", domain_id=domain.id)

    assert await _ids(session, item) == [on_domain.id]


@pytest.mark.asyncio
async def test_an_unknown_event_is_a_value_error(session):
    item = await _item(session)
    with pytest.raises(ValueError, match="digest"):
        await subs.subscriptions_for(session, item.info_item_id, "digest")


@pytest.mark.asyncio
async def test_count_for_domain_counts_its_domain_scope_rows(session):
    domain = await _domain(session, "counted.example.com")
    await _sub(session, "domain", domain_id=domain.id)
    await _sub(session, "domain", domain_id=domain.id, is_active=False)
    await _sub(session)

    assert await subs.count_for_domain(session, domain.id) == 2


@pytest.mark.asyncio
async def test_notified_by_lists_each_subscription_once_with_the_events_it_hears(session):
    domain = await _domain(session, "heard.example.com")
    item = await _item(session, "heard.example.com")
    g = await _sub(session, events=["watch_recovered", "change_detected"])
    d = await _sub(session, "domain", domain_id=domain.id, events=["watch_error"])
    await _sub(session, is_active=False)

    heard = await subs.notified_by(session, item.info_item_id)

    assert sorted((s.id, events) for s, events in heard) == sorted(
        [(g.id, ["change_detected", "watch_recovered"]), (d.id, ["watch_error"])]
    )


@pytest.mark.asyncio
async def test_create_waits_for_a_racing_domain_delete_and_then_refuses(
    test_engine, committed_rows
):
    """CR 1: the ref is read FOR KEY SHARE, so a create racing a Domain delete
    gets a clean refusal (no row), never a FK violation."""
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    async with factory() as setup:
        domain = Domain(name="race363.example.com")
        setup.add(domain)
        await setup.commit()
    committed_rows.append((Domain, domain.id))

    async with factory() as deleter, factory() as creator:
        assert await domain_policy.delete_domain(deleter, "race363.example.com") is True
        create = asyncio.create_task(
            subs.create_subscription(
                creator,
                title="racer",
                scope="domain",
                domain="race363.example.com",
                events=["change_detected"],
                remote_channel_id=CHANNEL,
            )
        )
        await asyncio.sleep(0.3)
        assert not create.done(), "the create should wait on the delete's row lock"
        await deleter.commit()
        with pytest.raises(subs.SubscriptionRefused, match="no Domain row"):
            await create
        await creator.rollback()
