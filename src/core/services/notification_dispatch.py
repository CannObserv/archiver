"""Compose a fact for each subscription that hears it, and record the rows (archiver#369, D1-D3).

The consumer's write. Per ``info.watch-events`` fact:

1. **Already recorded?** A fact with rows is acked without composing: the
   unique key would make the insert a no-op anyway, and composing again would
   re-read two texts from the processor bucket for nothing.
2. **Match.** ``load_item_facts`` and ``subscriptions_for``, once per fact. An
   unknown or revoked item raises :class:`UnknownInfoItemError` (ack and drop).
   **An archived, paused or host-suspended item still gets its fact** (D2): the
   fact happened before the state changed, and Watcher would have sent it.
3. **Compose**, outside any transaction: one diff per fact, read only if some
   row's options ask for one, then ``compose`` per subscription in a worker
   thread, so a slow template doesn't stall the loop (D7).
4. **Record**, in one short transaction: the subscriptions are re-read
   ``FOR KEY SHARE``, so one deleted meanwhile is dropped here rather than
   failing the insert (the #363 CR 1 lesson), and each row goes in with
   ``ON CONFLICT DO NOTHING``. The caller acks after this commits.

Each row's ``mode`` is the cutover's (D3): ``send`` (``pending``) only when T is
set and the fact occurred at or after it, otherwise ``shadow``. Nothing here
calls Notifier; the drain does (``notification_drain``).
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError
from sqlalchemy import exists, select
from sqlalchemy.dialects.postgresql import insert
from ulid import ULID

from src.core.logging import get_logger
from src.core.models import NotificationDispatch, NotificationSubscription
from src.core.notifications.content import WatchEvent, compose, resolve_options
from src.core.notifications.content_config import ContentOptions
from src.core.notifications.cutover import mode_for
from src.core.notifications.diff import ChangeDiff, diff_requested
from src.core.notifications.diff_loader import load_change_diff
from src.core.notifications.item_facts import load_item_facts
from src.core.services.notification_subscriptions import subscriptions_for

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from src.core.notifications.content import ItemFacts
    from src.core.notifications.diff_loader import TextReader

logger = get_logger(__name__)


class UnknownInfoItemError(LookupError):
    """The fact names an item the registry doesn't hold, or has revoked: ack and drop."""


class InvalidFactError(ValueError):
    """The fact decoded but can never be used (its ``info_item_id`` isn't a ULID): poison."""


def idempotency_key(event_type: str, subscription_id: ULID | str, event_id: str) -> str:
    """Notifier's key for a fact: ``archiver:{event}:{subscription_id}:{event_id}``."""
    return f"archiver:{event_type}:{subscription_id}:{event_id}"


def reminder_key(subscription_id: ULID | str, episode_event_id: str, n: int) -> str:
    """Notifier's key for the ``n``-th reminder of an error episode (D5)."""
    return f"archiver:watch_error_reminder:{subscription_id}:{episode_event_id}:{n}"


def parse_item_id(event: WatchEvent) -> ULID:
    """The fact's ``info_item_id`` as a ULID. Raises :class:`InvalidFactError`."""
    try:
        return ULID.from_str(event.info_item_id)
    except ValueError as e:
        raise InvalidFactError(f"info_item_id {event.info_item_id!r} is not a ULID") from e


def options_for(sub: NotificationSubscription, event_type: str) -> ContentOptions:
    """The row's options for ``event_type``, or the defaults if its stored document drifted.

    A stored ``content_config`` today's validator refuses (what
    ``audit_stored_documents`` sweeps for) must not stall the fact for every
    other subscription, or wedge the reminder timer (CR 1). A WARNING names the
    subscription and the error's type, never the document.
    """
    try:
        return resolve_options(sub.content_config, event_type)
    except ValidationError as e:
        logger.warning(
            "stored content options fail validation; composing with the defaults",
            extra={
                "subscription_id": str(sub.id),
                "event_type": event_type,
                "error_type": type(e).__name__,
            },
        )
        return ContentOptions()


@dataclass(frozen=True, slots=True)
class SubscriptionMatch:
    """One subscription that hears the fact, read as plain values."""

    subscription_id: ULID
    remote_channel_id: str
    options: ContentOptions


@dataclass(frozen=True, slots=True)
class PlannedRow:
    """A composed row, before it is recorded."""

    subscription_id: ULID
    remote_channel_id: str
    title: str
    body: str
    idempotency_key: str
    reminder: int = 0
    reminded_at: datetime | None = None


async def record_fact(
    session_factory: async_sessionmaker[AsyncSession],
    event: WatchEvent,
    *,
    text_reader: TextReader | None,
    cutover: datetime | None,
) -> int:
    """Compose and record one fact's rows. Returns how many were inserted.

    Raises:
        InvalidFactError: the ``info_item_id`` is not a ULID (poison).
        UnknownInfoItemError: no such item (ack and drop).
    """
    item_id = parse_item_id(event)
    async with session_factory() as session:
        if await _already_recorded(session, event.event_id):
            return 0
        item = await load_item_facts(session, item_id)
        if item is None:
            raise UnknownInfoItemError(event.info_item_id)
        matches = [
            SubscriptionMatch(sub.id, sub.remote_channel_id, options_for(sub, event.event_type))
            for sub in await subscriptions_for(session, item_id, event.event_type)
        ]
    if not matches:
        return 0

    diff = await _diff_for(event, matches, text_reader)
    rows = [
        PlannedRow(
            subscription_id=match.subscription_id,
            remote_channel_id=match.remote_channel_id,
            idempotency_key=idempotency_key(
                event.event_type, match.subscription_id, event.event_id
            ),
            **await compose_row(event, item, match, diff=diff),
        )
        for match in matches
    ]
    mode = mode_for(event.occurred_at, cutover)
    async with session_factory() as session:
        inserted = await insert_rows(session, event, rows, mode=mode)
        await session.commit()
    return inserted


async def _already_recorded(session: AsyncSession, event_id: str) -> bool:
    return bool(
        await session.scalar(
            select(
                exists().where(
                    NotificationDispatch.event_id == event_id, NotificationDispatch.reminder == 0
                )
            )
        )
    )


async def _diff_for(
    event: WatchEvent, matches: Sequence[SubscriptionMatch], text_reader: TextReader | None
) -> ChangeDiff | None:
    """One diff per fact, and only when a change has a row that would show it."""
    if event.event_type != "change_detected":
        return None
    if not any(diff_requested(m.options) for m in matches):
        return None
    return await load_change_diff(text_reader, event)


async def compose_row(
    event: WatchEvent,
    item: ItemFacts,
    match: SubscriptionMatch,
    *,
    diff: ChangeDiff | None,
    previously_notified_at: datetime | None = None,
) -> dict[str, str]:
    """``compose`` off the loop (D7): a saved template renders on every fact."""
    composed = await asyncio.to_thread(
        compose,
        event,
        item,
        match.options,
        diff=diff,
        previously_notified_at=previously_notified_at,
        subscription_id=str(match.subscription_id),
    )
    return {"title": composed.title, "body": composed.body}


async def insert_rows(
    session: AsyncSession,
    event: WatchEvent,
    rows: Sequence[PlannedRow],
    *,
    mode: str,
) -> int:
    """Insert ``rows`` for ``event``; returns how many were new. The caller commits.

    The subscriptions are taken ``FOR KEY SHARE`` first: a delete racing this
    insert waits for the commit and then nulls the ref, instead of failing the
    insert. A row whose subscription is already gone is dropped.
    """
    if not rows:
        return 0
    alive = set(
        (
            await session.execute(
                select(NotificationSubscription.id)
                .where(NotificationSubscription.id.in_([r.subscription_id for r in rows]))
                .with_for_update(key_share=True)
            )
        )
        .scalars()
        .all()
    )
    values: list[dict[str, Any]] = [
        {
            "id": ULID(),
            "event_id": event.event_id,
            "reminder": row.reminder,
            "event_type": event.event_type,
            "subscription_id": row.subscription_id,
            "info_item_id": ULID.from_str(event.info_item_id),
            "remote_channel_id": row.remote_channel_id,
            "occurred_at": event.occurred_at,
            "reminded_at": row.reminded_at,
            "fact": event.model_dump(mode="json"),
            "title": row.title,
            "body": row.body,
            "mode": mode,
            "status": "pending" if mode == "send" else "shadow",
            "idempotency_key": row.idempotency_key,
        }
        for row in rows
        if row.subscription_id in alive
    ]
    if not values:
        return 0
    result = await session.execute(
        insert(NotificationDispatch)
        .values(values)
        .on_conflict_do_nothing()
        .returning(NotificationDispatch.id)
    )
    return len(result.all())
