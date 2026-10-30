"""``load_item_facts``: what the composer knows about an item (archiver#367, D1).

The name and description are the InfoItem's. The URL and ``domain_name`` are
its **announcing** source's (the active binding), the rule ``subscriptions_for``
uses. ``check_interval`` is the resolved cadence, the value Watcher is told.
Tags stay empty until #362.
"""

from datetime import UTC, datetime

from sqlalchemy import update
from ulid import ULID

from src.core.models import Domain, InfoItem, InfoItemSource, InfoSource
from src.core.notifications.content import ItemFacts
from src.core.notifications.item_facts import load_item_facts

_SPECS = [{"schema_version": 1, "extraction": {"algorithm": "css", "selector": "body"}}]


async def _item(session, **kw) -> InfoItem:
    item = InfoItem(name="Licensing page", **kw)
    session.add(item)
    await session.flush()
    return item


async def _bind(session, item: InfoItem, host: str) -> InfoSource:
    source = InfoSource(url=f"https://{host}/page", source_specs=_SPECS, domain_name=host)
    session.add(source)
    await session.flush()
    session.add(
        InfoItemSource(info_item_id=item.info_item_id, info_source_id=source.info_source_id)
    )
    await session.flush()
    return source


async def test_an_unknown_item_is_none(session):
    assert await load_item_facts(session, ULID()) is None


async def test_an_unbound_item_has_its_own_facts_only(session):
    item = await _item(session, description="Renewals")
    assert await load_item_facts(session, item.info_item_id) == ItemFacts(
        name="Licensing page", description="Renewals"
    )


async def test_the_announcing_source_gives_url_and_domain(session):
    item = await _item(session, watch_spec={"schema_version": 1, "interval": "6h"})
    source = await _bind(session, item, "facts.example.com")
    facts = await load_item_facts(session, str(item.info_item_id))
    assert facts.url == source.url
    assert facts.domain_name == "facts.example.com"
    assert facts.check_interval == "6h"
    assert facts.tags == ()


async def test_the_interval_falls_back_to_the_domain_tier(session):
    item = await _item(session)
    await _bind(session, item, "tier.example.com")
    session.add(
        Domain(name="tier.example.com", default_watch_spec={"schema_version": 1, "interval": "1d"})
    )
    await session.flush()
    facts = await load_item_facts(session, item.info_item_id)
    assert facts.check_interval == "1d"


async def test_a_deactivated_binding_is_not_the_announcing_source(session):
    item = await _item(session)
    await _bind(session, item, "old.example.com")
    await session.execute(
        update(InfoItemSource)
        .where(InfoItemSource.info_item_id == item.info_item_id)
        .values(deactivated_at=datetime.now(UTC))
    )
    facts = await load_item_facts(session, item.info_item_id)
    assert facts.url == ""
    assert facts.domain_name == ""
