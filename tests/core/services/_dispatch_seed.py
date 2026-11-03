"""Seed rows for the #369 dispatch tests, which commit for real.

The consumer, the drain and the reminder timer each open their own sessions, so
the savepoint-scoped ``session`` fixture would be invisible to them. A module
using these marks itself with ``clean_dispatch_tables`` (``tests/core/conftest.py``).
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.models import (
    Domain,
    InfoItem,
    InfoItemSource,
    InfoSource,
    NotificationSubscription,
    WatchStatus,
)

DEV_SINK = "01M5APS9R7A0QEDB9522MRA4CT"
OTHER_CHANNEL = "01M5APS9R7A0QEDB9522MRA4CV"
_SPECS = [{"schema_version": 1, "extraction": {"algorithm": "css", "selector": "body"}}]

TRUNCATE = (
    "TRUNCATE TABLE information.notification_dispatches CASCADE",
    "TRUNCATE TABLE information.notification_subscriptions CASCADE",
    "TRUNCATE TABLE information.watch_status CASCADE",
    "TRUNCATE TABLE information.info_items CASCADE",
    "TRUNCATE TABLE information.info_sources CASCADE",
    "TRUNCATE TABLE information.domains CASCADE",
)


async def seed_item(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    host: str = "dispatch.example.com",
    name: str = "Licensing page",
    **item_fields,
) -> InfoItem:
    """An item bound to a source on ``host``, with a Domain row for the host."""
    async with session_factory() as session:
        if (
            await session.scalar(
                text("SELECT count(*) FROM information.domains WHERE name = :n").bindparams(n=host)
            )
            == 0
        ):
            session.add(Domain(name=host))
        item = InfoItem(name=name, **item_fields)
        source = InfoSource(url=f"https://{host}/page", source_specs=_SPECS, domain_name=host)
        session.add_all([item, source])
        await session.flush()
        session.add(
            InfoItemSource(info_item_id=item.info_item_id, info_source_id=source.info_source_id)
        )
        await session.commit()
        return item


async def seed_subscription(
    session_factory: async_sessionmaker[AsyncSession], **fields
) -> NotificationSubscription:
    row = {
        "title": "Ops",
        "scope": "global",
        "events": ["change_detected", "watch_error", "watch_recovered"],
        "remote_channel_id": DEV_SINK,
    } | fields
    async with session_factory() as session:
        sub = NotificationSubscription(**row)
        session.add(sub)
        await session.commit()
        return sub


async def seed_watch_status(
    session_factory: async_sessionmaker[AsyncSession], item: InfoItem, health: str
) -> None:
    async with session_factory() as session:
        session.add(
            WatchStatus(
                info_item_id=item.info_item_id,
                applied_generation=1,
                applied_active=True,
                health=health,
                occurred_at=datetime.now(UTC),
            )
        )
        await session.commit()
