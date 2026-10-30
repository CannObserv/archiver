"""What the composer knows about an item, loaded from the registry (archiver#367, D1).

D1's rules, in one place so #369 doesn't re-derive them:

- ``name`` and ``description`` are the InfoItem's;
- ``url`` and ``domain_name`` are its **announcing** source's, the source on the
  active binding. That is the rule ``subscriptions_for`` matches domain scope by,
  so a notification names the host it was routed by;
- ``check_interval`` is ``resolve_interval`` (profile, then item, then domain):
  the cadence Watcher is told;
- ``tags`` is empty until #362.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.core.models import Domain, InfoItem, InfoItemSource, InfoSource, TemporalProfile
from src.core.notifications.content import ItemFacts
from src.core.services.cadence_resolution import resolve_interval


async def load_item_facts(session: AsyncSession, info_item_id: ULID | str) -> ItemFacts | None:
    """The item's facts, or ``None`` when no such item exists."""
    key = ULID.from_str(info_item_id) if isinstance(info_item_id, str) else info_item_id
    item = await session.get(InfoItem, key)
    if item is None:
        return None
    source = (
        await session.execute(
            select(InfoSource)
            .join(InfoItemSource, InfoItemSource.info_source_id == InfoSource.info_source_id)
            .where(InfoItemSource.info_item_id == key, InfoItemSource.deactivated_at.is_(None))
        )
    ).scalar_one_or_none()
    host = source.domain_name if source is not None else None
    domain = (
        (await session.execute(select(Domain).where(Domain.name == host))).scalar_one_or_none()
        if host
        else None
    )
    profile = await session.get(TemporalProfile, key)
    interval = resolve_interval(profile=profile, item=item, domain=domain).interval
    return ItemFacts(
        name=item.name,
        url=source.url if source is not None else "",
        domain_name=host or "",
        description=item.description or "",
        check_interval=interval or "",
    )
