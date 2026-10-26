"""Domain writes that can suspend or resume a host (archiver#360).

Suspension is intent: an inactive or archived ``Domain`` resolves
``active=false`` on every item announced on its host (``domain_suspended``,
``src.core.services.registry_announcement``). So a write that flips it is a
policy write on each of those items, and it announces them in its own
transaction — the API ``PATCH``, archive and restore, and the dashboard's
archive, restore and fetch-policy save all come through ``update_domain``.

**Only what changed is announced.** A flip touches the items whose resolved
``active`` moves: announceable, and ``watch_active`` not already ``false``. A
write that flips nothing — notes, ``min_interval_seconds``, the cadence,
archiving an already-inactive host — emits nothing (the #167 rule).

**Lock order: items, then the Domain row**, the order every announce takes
them in (``registry_announcement``'s module docstring), for a write that
touches ``SUSPENSION_COLUMNS``; any other write locks the row alone, ``FOR NO
KEY UPDATE``, which announces never wait on. Locking the items first
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

**The host's ``content.fetch-policy`` frame rides the same write** (archiver#366).
When the frame changes - an interval save on a live host, a suspension flip -
or this call inserted the row, ``announce_domain`` draws the next generation
under the row lock already held and queues the frame. It takes no other lock,
so the order above stands. ``delete_domain`` locks the row before it draws
the tombstone's value, so a save that held the row first always orders below it.
"""

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.core.models import Domain, InfoItem, InfoItemSource, InfoSource
from src.core.services.fetch_policy import (
    announce_domain,
    announce_domain_deleted,
    policy_frame,
)
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


async def _insert_if_absent(session: AsyncSession, name: str) -> bool:
    """Insert the host's row unless it exists; returns whether this call inserted it."""
    inserted = await session.execute(
        pg_insert(Domain)
        .values(name=name)
        .on_conflict_do_nothing(index_elements=["name"])
        .returning(Domain.id)
    )
    return inserted.first() is not None


async def _lock_row(
    session: AsyncSession, name: str, *, create: bool, can_flip: bool = True
) -> tuple[Domain | None, bool]:
    """Insert the row if asked, then lock it; returns ``(row, inserted)``.

    ``FOR UPDATE`` for a write that can flip suspension: it is what an
    announce's ``FOR KEY SHARE`` waits on. Any other write takes ``FOR NO KEY
    UPDATE``, which announces do not wait on (CR 24).
    """
    # A DELETE committing between this and the lock leaves no row: None,
    # which the API answers with a 409 (CR 15, 26).
    inserted = create and await _insert_if_absent(session, name)
    domain = (
        await session.execute(
            select(Domain)
            .where(Domain.name == name)
            .with_for_update(key_share=not can_flip)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    return domain, inserted


async def _apply(
    session: AsyncSession, domain: Domain, changes: Mapping[str, Any], *, inserted: bool
) -> None:
    """Write ``changes`` and announce the host's fetch-policy frame if it moved."""
    before = policy_frame(domain)
    for column, value in changes.items():
        setattr(domain, column, value)
    await session.flush()
    if inserted or policy_frame(domain) != before:
        await announce_domain(session, domain)


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
        domain, inserted = await _lock_row(session, name, create=create, can_flip=False)
        if domain is not None:
            await _apply(session, domain, changes, inserted=inserted)
        return domain

    locked = await _host_items(session, name, lock=True)
    for attempt in range(_ATTEMPTS):
        savepoint = await session.begin_nested()
        domain, inserted = await _lock_row(session, name, create=create)
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
    await _apply(session, domain, changes, inserted=inserted)
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


class DomainInUse(Exception):
    """The host still has InfoSources naming it; nothing was deleted."""

    def __init__(self, count: int):
        super().__init__(f"{count} InfoSource(s) reference the domain")
        self.count = count


async def delete_domain(session: AsyncSession, name: str) -> bool:
    """Delete the host's row and record its ``content.fetch-policy`` tombstone.

    Returns ``False`` when there is no row. Raises ``DomainInUse`` while any
    InfoSource names the host. The row is locked **before** the tombstone's
    generation is drawn (archiver#366): a write that holds it - an interval
    save mid-transaction - has drawn its own value by then and commits first,
    so the tombstone always orders above it. Drawn before the lock, it could
    land below that save's live frame, and every consumer would keep the
    deleted host live. No items to lock: a host with sources is refused. The
    caller commits.
    """
    domain = (
        await session.execute(
            select(Domain)
            .where(Domain.name == name)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if domain is None:
        return False
    count = (
        await session.execute(
            select(func.count()).select_from(InfoSource).where(InfoSource.domain_name == name)
        )
    ).scalar_one()
    if count:
        raise DomainInUse(count)
    await announce_domain_deleted(session, name)
    await session.delete(domain)
    await session.flush()
    return True
