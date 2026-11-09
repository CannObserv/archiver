"""``load_item_facts``: what the composer knows about an item (archiver#367, D1).

The name and description are the InfoItem's. The URL and ``domain_name`` are
its **announcing** source's (the active binding), the rule ``subscriptions_for``
uses. ``check_interval`` is the resolved cadence, the value Watcher is told.
``tags`` are the item's own, as stored (archiver#362).
"""

from datetime import UTC, datetime

from sqlalchemy import update
from ulid import ULID

from src.core.models import Domain, InfoItem, InfoItemSource, InfoSource
from src.core.notifications.content import ItemFacts, build_body
from src.core.notifications.content_config import ContentOptions
from src.core.notifications.item_facts import load_item_facts
from tests.core.notifications.builders import make_event

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


async def test_the_items_tags_are_its_facts(session):
    """archiver#362 D5: in the column's order - the tag service stores them sorted."""
    item = await _item(session, tags=["license", "cannabis"])
    facts = await load_item_facts(session, item.info_item_id)
    assert facts.tags == ("license", "cannabis")


async def test_an_untagged_item_has_no_tags(session):
    item = await _item(session)
    assert (await load_item_facts(session, item.info_item_id)).tags == ()


async def test_include_tags_puts_the_items_tags_on_the_tags_line(session):
    """The composer's TAGS line, from the registry rather than a canned item."""
    item = await _item(session, tags=["cannabis", "license"])
    facts = await load_item_facts(session, item.info_item_id)
    event = make_event()

    assert "TAGS: cannabis, license" in build_body(event, facts, ContentOptions(include_tags=True))
    assert "TAGS" not in build_body(event, facts, ContentOptions())
