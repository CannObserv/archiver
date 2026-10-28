"""Notification subscriptions: who hears, and the writes (archiver#363, D2).

``subscriptions_for`` is **the** matcher: #367's preview and #369's dispatch
both call it, and the item page's "Notified by" row shows its result, so who
hears is defined once, before anything sends. It is Watcher's rule
(``notify.py`` at ``ebd1be5``): every active subscription whose ``events`` hold
the event, in the union of three scopes -

- ``global``: every item;
- ``domain``: items whose **announcing** source's host (the active binding's
  ``InfoSource.domain_name``) is the Domain row's ``name``. An item with no
  active binding, or on a host with no Domain row, matches none;
- ``item``: that item.

Each row matches once; no scope overrides another, and there is no
channel-level dedup (watcher #200 F2). Archive, pause and host suspension
filter nothing - Watcher checks none of those items, so no event arrives.

**The writes** (``create_subscription``, ``update_subscription``) are shared
by the API and the dashboard. The scope and its ref are fixed at create:
re-scoping is delete and create (Watcher's ``MUTABLE_TEMPLATE_FIELDS``).
Content validation is the caller's (``src.core.notifications.content_config``).

Nothing here sends or publishes: subscriptions are not on any stream.
"""

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.core.models import (
    Domain,
    InfoItem,
    InfoItemSource,
    InfoSource,
    NotificationSubscription,
)
from src.core.models.notification_subscription import NOTIFICATION_EVENTS

MUTABLE_FIELDS = frozenset({"title", "events", "remote_channel_id", "is_active", "content_config"})
"""What an update may assign; the scope, its ref and ``imported_watcher_id`` are fixed."""

_IMPORT_KEY = "uq_notification_subscriptions_imported_watcher_id"


class SubscriptionRefused(ValueError):
    """The write does not describe a valid subscription; ``errors`` are (path, message)."""

    def __init__(self, errors: list[tuple[str, str]]):
        super().__init__("; ".join(f"{path}: {message}" for path, message in errors))
        self.errors = errors


class ImportKeyTaken(Exception):
    """Another subscription already carries this ``imported_watcher_id``."""


def canonical_events(events: Iterable[str]) -> list[str]:
    """``events`` de-duplicated, in declaration order. Raises ``SubscriptionRefused``."""
    wanted = set(events)
    unknown = sorted(wanted - set(NOTIFICATION_EVENTS))
    if unknown:
        raise SubscriptionRefused([("/events", f"unknown event(s): {', '.join(unknown)}")])
    if not wanted:
        raise SubscriptionRefused([("/events", "at least one event is required")])
    return [e for e in NOTIFICATION_EVENTS if e in wanted]


def _ref_errors(scope: str, domain: str | None, info_item_id: str | None) -> list[tuple]:
    """Each ref the scope does not take, and the one it needs but lacks."""
    errors = []
    if scope == "domain" and domain is None:
        errors.append(("/domain", "domain scope needs a domain"))
    if scope != "domain" and domain is not None:
        errors.append(("/domain", f"{scope} scope takes no domain"))
    if scope == "item" and info_item_id is None:
        errors.append(("/info_item_id", "item scope needs an info_item_id"))
    if scope != "item" and info_item_id is not None:
        errors.append(("/info_item_id", f"{scope} scope takes no info_item_id"))
    return errors


async def create_subscription(
    session: AsyncSession,
    *,
    title: str,
    scope: str,
    events: Iterable[str],
    remote_channel_id: str,
    domain: str | None = None,
    info_item_id: str | None = None,
    is_active: bool = True,
    content_config: dict[str, Any] | None = None,
    imported_watcher_id: str | None = None,
) -> NotificationSubscription:
    """Insert one subscription and flush it; the caller commits.

    ``domain`` is a hostname, resolved to its Domain row. Raises
    ``SubscriptionRefused`` when the ref does not fit the scope or names no row,
    and ``ImportKeyTaken`` on a duplicate ``imported_watcher_id``.
    """
    errors = _ref_errors(scope, domain, info_item_id)
    if errors:
        raise SubscriptionRefused(errors)
    domain_id = None
    if domain is not None:
        domain_id = (
            await session.execute(select(Domain.id).where(Domain.name == domain))
        ).scalar_one_or_none()
        if domain_id is None:
            raise SubscriptionRefused([("/domain", f"no Domain row named {domain!r}")])
    if info_item_id is not None and await session.get(InfoItem, info_item_id) is None:
        raise SubscriptionRefused([("/info_item_id", "InfoItem not found")])
    sub = NotificationSubscription(
        title=title,
        scope=scope,
        domain_id=domain_id,
        info_item_id=info_item_id,
        events=canonical_events(events),
        remote_channel_id=remote_channel_id,
        is_active=is_active,
        content_config=content_config,
        imported_watcher_id=imported_watcher_id,
    )
    try:
        async with session.begin_nested():
            session.add(sub)
            await session.flush()
    except IntegrityError as e:
        if _IMPORT_KEY in str(e.orig):
            raise ImportKeyTaken(imported_watcher_id) from e
        raise
    return sub


def update_subscription(
    sub: NotificationSubscription, changes: Mapping[str, Any]
) -> NotificationSubscription:
    """Assign the given mutable fields; ``content_config`` is replaced whole.

    Raises ``ValueError`` on any other field: the scope and its ref are fixed.
    """
    fixed = set(changes) - MUTABLE_FIELDS
    if fixed:
        raise ValueError(f"immutable or unknown subscription fields: {sorted(fixed)}")
    for field, value in changes.items():
        setattr(sub, field, canonical_events(value) if field == "events" else value)
    return sub


def _announcing_host(info_item_id: ULID | str):
    """The active binding's source host, as a scalar subquery (``NULL`` when unbound)."""
    return (
        select(InfoSource.domain_name)
        .join(InfoItemSource, InfoItemSource.info_source_id == InfoSource.info_source_id)
        .where(
            InfoItemSource.info_item_id == info_item_id,
            InfoItemSource.deactivated_at.is_(None),
        )
        .scalar_subquery()
    )


async def subscriptions_for(
    session: AsyncSession, info_item_id: ULID | str, event: str
) -> Sequence[NotificationSubscription]:
    """The active subscriptions that hear ``event`` on the item, in id order.

    Raises ``ValueError`` on an event that is not one of the three.
    """
    if event not in NOTIFICATION_EVENTS:
        raise ValueError(f"unknown notification event {event!r}")
    host_domain = select(Domain.id).where(Domain.name == _announcing_host(info_item_id))
    stmt = (
        select(NotificationSubscription)
        .where(
            NotificationSubscription.is_active.is_(True),
            NotificationSubscription.events.contains([event]),
            or_(
                NotificationSubscription.scope == "global",
                and_(
                    NotificationSubscription.scope == "item",
                    NotificationSubscription.info_item_id == info_item_id,
                ),
                and_(
                    NotificationSubscription.scope == "domain",
                    NotificationSubscription.domain_id.in_(host_domain),
                ),
            ),
        )
        .order_by(NotificationSubscription.id)
    )
    return (await session.execute(stmt)).scalars().all()


async def count_for_domain(session: AsyncSession, domain_id: ULID | str) -> int:
    """How many subscriptions name the Domain row, active or not (its delete's 409)."""
    return (
        await session.execute(
            select(func.count())
            .select_from(NotificationSubscription)
            .where(NotificationSubscription.domain_id == domain_id)
        )
    ).scalar_one()
