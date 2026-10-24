"""Domain writes that can suspend or resume a host (archiver#360).

Suspension is intent: an inactive or archived ``Domain`` resolves
``active=false`` on every item announced on its host (``domain_suspended``,
``src.core.services.registry_announcement``). So a write that flips it is a
policy write on each of those items, and it announces them in its own
transaction — the API ``PATCH``, archive and restore, and the dashboard's
archive and restore all come through ``update_domain``.

**Only what changed is announced.** A flip touches the items whose resolved
``active`` moves: announceable, and ``watch_active`` not already ``false``. A
write that flips nothing — notes, ``min_interval_seconds``, the cadence,
archiving an already-inactive host — emits nothing (the #167 rule).

**Lock order: items, then the Domain row** — for a write that touches
``SUSPENSION_COLUMNS``; any other write locks the row alone. The order every announce takes
them in (``registry_announcement``'s module docstring). Locking the items first
would still miss one bound to the host while this write waited for the row, so
the host's items are re-read once the row is held: any announce that bound one
held the row ``FOR KEY SHARE``, so it has committed by then and the re-read
sees it. A newcomer is never locked *after* the row, which would invert the
order and deadlock against an announce holding it (CR 2): the row is taken in a
savepoint, given back, and the newcomers locked first, then the row again. Only
a host still gaining items after three tries locks them after the row.

**Accepted limit (CR 3):** a host with *no* row has nothing to lock. Creating
it inactive while a binding to it announces can miss that one item, since the
binding's share lock matches nothing. Every source create makes the row
(``get_or_create_domain``), and production had no row-less sources at #360.
"""

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.core.models import Domain, InfoItem, InfoItemSource, InfoSource
from src.core.services.registry_announcement import (
    announce_policy_changes,
    domain_suspended,
)

WRITABLE_COLUMNS = frozenset(
    {
        "notes",
        "is_active",
        "archived_at",
        "min_interval_seconds",
        "default_watch_spec",
        "updated_at",
    }
)


async def _host_items(session: AsyncSession, name: str, *, lock: bool) -> list[ULID]:
    """Items whose active binding's source names ``name``, in id order."""
    stmt = (
        select(InfoItem.info_item_id)
        .where(
            InfoItem.info_item_id.in_(
                select(InfoItemSource.info_item_id)
                .join(InfoSource, InfoSource.info_source_id == InfoItemSource.info_source_id)
                .where(InfoSource.domain_name == name, InfoItemSource.deactivated_at.is_(None))
            )
        )
        .order_by(InfoItem.info_item_id)
    )
    if lock:
        stmt = stmt.with_for_update()
    return list((await session.execute(stmt)).scalars())


SUSPENSION_COLUMNS = frozenset({"is_active", "archived_at"})
"""The only columns ``domain_suspended`` reads; a write touching neither cannot flip."""

_ATTEMPTS = 3
"""How many times the write re-locks before it locks a newcomer after the row."""


async def _lock_row(session: AsyncSession, name: str, *, create: bool) -> Domain | None:
    if create:
        await session.execute(
            pg_insert(Domain).values(name=name).on_conflict_do_nothing(index_elements=["name"])
        )
    return (
        await session.execute(
            select(Domain)
            .where(Domain.name == name)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


async def update_domain(
    session: AsyncSession, name: str, changes: Mapping[str, Any], *, create: bool
) -> Domain | None:
    """Apply ``changes`` to the host's Domain and announce what a flip changed.

    ``create`` inserts the row when absent (the API's upsert); otherwise a
    missing row returns ``None`` and writes nothing. A row-less host counts as
    active, so creating it inactive is a flip. The caller commits.
    """
    unknown = set(changes) - WRITABLE_COLUMNS
    if unknown:
        raise ValueError(f"not writable on a Domain: {sorted(unknown)}")

    if not changes.keys() & SUSPENSION_COLUMNS:
        # Cannot flip, so nothing to announce and no item lock to take (CR 13).
        domain = await _lock_row(session, name, create=create)
        if domain is not None:
            for column, value in changes.items():
                setattr(domain, column, value)
            await session.flush()
        return domain

    locked = await _host_items(session, name, lock=True)
    for attempt in range(_ATTEMPTS):
        savepoint = await session.begin_nested()
        domain = await _lock_row(session, name, create=create)
        if domain is None:
            await savepoint.commit()
            return None
        held = set(locked)
        newcomers = [i for i in await _host_items(session, name, lock=False) if i not in held]
        if not newcomers:
            break
        if attempt == _ATTEMPTS - 1:
            # Still churning: lock them after the row, the one place the order
            # inverts. Postgres's deadlock detector is the backstop (CR 2).
            locked = [*locked, *newcomers]
            break
        # Give the row back, then take the newcomers in item order (CR 2).
        await savepoint.rollback()
        locked = await _host_items(session, name, lock=True)

    # A row this call inserted was absent a moment ago, and absent is active.
    was_suspended = domain_suspended(domain)
    for column, value in changes.items():
        setattr(domain, column, value)
    await session.flush()
    await savepoint.commit()
    if domain_suspended(domain) != was_suspended:
        await _announce_flip(session, locked)
    return domain


async def _announce_flip(session: AsyncSession, items: Sequence[ULID]) -> int:
    """Announce every item on the host whose resolved ``active`` just moved."""
    if not items:
        return 0
    moved = (
        (
            await session.execute(
                select(InfoItem.info_item_id)
                .where(
                    InfoItem.info_item_id.in_(items),
                    InfoItem.watch_active.is_distinct_from(False),
                )
                .order_by(InfoItem.info_item_id)
            )
        )
        .scalars()
        .all()
    )
    return await announce_policy_changes(session, moved)
