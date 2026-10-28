"""Notification subscriptions (archiver#363): ``/notification-subscriptions``.

Who hears which events, and how: a scope (global, a Domain, or one InfoItem),
an event set, content options and a Notifier channel. Matching is
``src.core.services.notification_subscriptions.subscriptions_for``. Nothing
here sends or publishes; composition is #367, dispatch #369.
"""

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db_session
from src.api.errors import FieldError, raise_422, raise_envelope
from src.api.schemas.notification_subscription import (
    NotificationSubscriptionCreate,
    NotificationSubscriptionOut,
    NotificationSubscriptionPatch,
)
from src.api.schemas.pagination import Page
from src.api.schemas.types import ULIDStr
from src.core.models import Domain, NotificationSubscription
from src.core.models.notification_subscription import Scope
from src.core.services import notification_subscriptions as subs

router = APIRouter(prefix="/notification-subscriptions", tags=["notification-subscriptions"])


def _to_out(sub: NotificationSubscription, domain: str | None) -> NotificationSubscriptionOut:
    return NotificationSubscriptionOut(
        id=str(sub.id),
        title=sub.title,
        scope=sub.scope,
        domain_id=str(sub.domain_id) if sub.domain_id else None,
        domain=domain,
        info_item_id=str(sub.info_item_id) if sub.info_item_id else None,
        events=sub.events,
        content_config=sub.content_config,
        remote_channel_id=sub.remote_channel_id,
        is_active=sub.is_active,
        imported_watcher_id=str(sub.imported_watcher_id) if sub.imported_watcher_id else None,
        created_at=sub.created_at,
        updated_at=sub.updated_at,
    )


def _with_domain():
    return select(NotificationSubscription, Domain.name).outerjoin(
        Domain, Domain.id == NotificationSubscription.domain_id
    )


async def _get_or_404(
    session: AsyncSession, subscription_id: str
) -> tuple[NotificationSubscription, str | None]:
    row = (
        await session.execute(_with_domain().where(NotificationSubscription.id == subscription_id))
    ).one_or_none()
    if row is None:
        raise_envelope(404, "lookup", "NotificationSubscription not found")
    return row[0], row[1]


@router.get("", response_model=Page[NotificationSubscriptionOut])
async def list_notification_subscriptions(
    scope: Scope | None = Query(default=None, description="Filter by scope."),
    domain: str | None = Query(
        default=None, description="Filter to domain-scoped subscriptions on this hostname."
    ),
    info_item_id: ULIDStr | None = Query(
        default=None, description="Filter to item-scoped subscriptions on this InfoItem."
    ),
    is_active: bool | None = Query(default=None, description="Filter by active status."),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0, le=2**63 - 1),
    session: AsyncSession = Depends(get_db_session),
) -> Page[NotificationSubscriptionOut]:
    """List subscriptions, oldest first, with offset pagination.

    The filters select rows by their own scope: ``domain`` returns that host's
    domain-scoped rows, not everything that would match an item on it. For
    who hears a given item, see the dashboard's item page.
    """
    stmt = _with_domain().order_by(NotificationSubscription.created_at, NotificationSubscription.id)
    if scope is not None:
        stmt = stmt.where(NotificationSubscription.scope == scope)
    if domain is not None:
        stmt = stmt.where(Domain.name == domain)
    if info_item_id is not None:
        stmt = stmt.where(NotificationSubscription.info_item_id == info_item_id)
    if is_active is not None:
        stmt = stmt.where(NotificationSubscription.is_active == is_active)
    rows = (await session.execute(stmt.offset(offset).limit(limit + 1))).all()
    return Page[NotificationSubscriptionOut](
        items=[_to_out(sub, name) for sub, name in rows[:limit]],
        has_more=len(rows) > limit,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=NotificationSubscriptionOut, status_code=201)
async def create_notification_subscription(
    body: NotificationSubscriptionCreate,
    session: AsyncSession = Depends(get_db_session),
) -> NotificationSubscriptionOut:
    """Create a subscription.

    ``scope`` takes exactly its ref (``domain`` a hostname with a Domain row,
    ``item`` an ``info_item_id``); a ref that does not fit, or names no row, is
    a 422 on that field. A duplicate ``imported_watcher_id`` is a 409.
    """
    try:
        sub = await subs.create_subscription(
            session,
            title=body.title,
            scope=body.scope,
            domain=body.domain,
            info_item_id=body.info_item_id,
            events=body.events,
            remote_channel_id=body.remote_channel_id,
            is_active=body.is_active,
            content_config=_stored(body.content_config),
            imported_watcher_id=body.imported_watcher_id,
        )
    except subs.SubscriptionRefused as e:
        _refuse(e)
    except subs.ImportKeyTaken as e:
        raise_envelope(
            409,
            "conflict",
            f"A subscription already carries imported_watcher_id {body.imported_watcher_id}.",
            source_exc=e,
        )
    await session.commit()
    return await _reread(session, sub)


@router.get("/{subscription_id}", response_model=NotificationSubscriptionOut)
async def get_notification_subscription(
    subscription_id: ULIDStr,
    session: AsyncSession = Depends(get_db_session),
) -> NotificationSubscriptionOut:
    """One subscription; 404 when missing."""
    sub, domain = await _get_or_404(session, subscription_id)
    return _to_out(sub, domain)


@router.patch("/{subscription_id}", response_model=NotificationSubscriptionOut)
async def update_notification_subscription(
    subscription_id: ULIDStr,
    body: NotificationSubscriptionPatch,
    session: AsyncSession = Depends(get_db_session),
) -> NotificationSubscriptionOut:
    """Change the fields sent. ``content_config`` is replaced whole (``null`` =
    all defaults). The scope, its ref and ``imported_watcher_id`` are fixed:
    re-scope by deleting and creating."""
    sub, _ = await _get_or_404(session, subscription_id)
    changes = {field: getattr(body, field) for field in body.model_fields_set}
    if "content_config" in changes:
        changes["content_config"] = _stored(body.content_config)
    try:
        subs.update_subscription(sub, changes)
    except subs.SubscriptionRefused as e:
        _refuse(e)
    await session.commit()
    return await _reread(session, sub)


@router.delete("/{subscription_id}", status_code=204)
async def delete_notification_subscription(
    subscription_id: ULIDStr,
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    """Delete a subscription; 404 when missing."""
    sub, _ = await _get_or_404(session, subscription_id)
    await session.delete(sub)
    await session.commit()
    return Response(status_code=204)


def _stored(config) -> dict | None:
    """What a write stores: the config as sent, without the defaults it omitted."""
    return None if config is None else config.model_dump(mode="json", exclude_unset=True)


def _refuse(e: subs.SubscriptionRefused) -> None:
    raise_422(
        "notification subscription failed validation",
        errors=[FieldError(path=path, message=message) for path, message in e.errors],
        source_exc=e,
    )


async def _reread(session: AsyncSession, sub: NotificationSubscription):
    await session.refresh(sub)
    return _to_out(*(await _get_or_404(session, str(sub.id))))
