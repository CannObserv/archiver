"""Error reminders and the dispatch table's retention (archiver#369, D5 and D1).

Watcher re-notified a persistent error on a failed check (#71). Design C-a moves
that cadence here, "timed from the ``WatchErrorEvent`` edge plus the ``health``
level", so Watcher emits nothing per failed check. A lifespan timer (every
15 min, the replication reaper's shape) does it:

- **Which items:** ``watch_status.health == "error"``, and Watcher still checks
  the item: not archived, not paused, host not suspended
  (``registry_announcement.resolved_active``). Unlike Watcher, a paused or
  archived item in error isn't reminded; Watcher couldn't remind it either,
  because nothing checks it.
- **The episode** is the item's newest ``watch_error`` row with no newer
  ``watch_recovered`` row. A newer error edge supersedes an open one (co-core's
  rule). An item in error with no episode row (an error from before the group
  existed, or one nobody heard) is skipped with an INFO line, never guessed.
- **Per subscription** that still hears ``watch_error`` and has a row in the
  episode: when its newest row (the edge, or its last reminder) is at least
  ``ARCHIVER_ERROR_RENOTIFY_INTERVAL`` old, the next reminder row goes in,
  keyed ``archiver:watch_error_reminder:{subscription_id}:{episode_event_id}:{n}``
  and composed with ``previously_notified_at``. **The state is the rows
  themselves**: no ``last_error_notified_at`` column.
- **Its mode is the reminder's own instant's** (D3).

The interval is service-wide, like Watcher's. The same timer prunes the table:
terminal rows past ``ARCHIVER_NOTIFY_RETENTION_DAYS`` (default 90, so F3's
parity window survives), in bounded batches, as ``outbox_prune`` does.
``pending`` rows are never pruned.
"""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from co_core.pure.models.changes import WatchErrorEvent
from sqlalchemy import delete, func, select
from ulid import ULID

from src.core.changes.backoff import ERROR_BACKOFF_BASE_SECONDS, error_backoff_seconds
from src.core.logging import get_logger
from src.core.models import (
    Domain,
    InfoItem,
    InfoItemSource,
    InfoSource,
    NotificationDispatch,
    WatchStatus,
)
from src.core.models.notification_dispatch import TERMINAL_STATUSES
from src.core.notifications.content import resolve_options
from src.core.notifications.cutover import mode_for
from src.core.notifications.item_facts import load_item_facts
from src.core.services.notification_dispatch import (
    PlannedRow,
    SubscriptionMatch,
    compose_row,
    insert_rows,
    reminder_key,
)
from src.core.services.notification_subscriptions import subscriptions_for
from src.core.services.registry_announcement import domain_suspended, resolved_active

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = get_logger(__name__)

RENOTIFY_INTERVAL_ENV = "ARCHIVER_ERROR_RENOTIFY_INTERVAL"
DEFAULT_RENOTIFY_INTERVAL = timedelta(hours=24)
NOTIFY_RETENTION_ENV = "ARCHIVER_NOTIFY_RETENTION_DAYS"
DEFAULT_RETENTION_DAYS = 90
#: How often the timer looks (D5).
TIMER_SECONDS = 900.0
PRUNE_BATCH_SIZE = 1_000
MAX_PRUNE_BATCHES = 10

# Watcher's cadence vocabulary: '30s', '15m', '6h', '1d'.
_INTERVAL = re.compile(r"(\d+)([smhd])")
_UNIT = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}


def resolve_renotify_interval(raw: str | None) -> timedelta:
    """``ARCHIVER_ERROR_RENOTIFY_INTERVAL``, Watcher's rule: malformed falls back and warns.

    Zero is honoured, and said: every tick of an open episode reminds.
    """
    if raw is None:
        return DEFAULT_RENOTIFY_INTERVAL
    match = _INTERVAL.fullmatch(raw.strip())
    if match is None:
        logger.warning(
            "unparseable %s — using the default",
            RENOTIFY_INTERVAL_ENV,
            extra={"value": raw, "default_hours": DEFAULT_RENOTIFY_INTERVAL / timedelta(hours=1)},
        )
        return DEFAULT_RENOTIFY_INTERVAL
    interval = timedelta(**{_UNIT[match.group(2)]: int(match.group(1))})
    if not interval:
        logger.info(
            "%s is zero — every timer tick re-notifies an open error", RENOTIFY_INTERVAL_ENV
        )
    return interval


def resolve_retention_days(raw: str | None) -> int | None:
    """``ARCHIVER_NOTIFY_RETENTION_DAYS``: days, or ``None`` (``<= 0``) to keep every row."""
    if raw is None:
        return DEFAULT_RETENTION_DAYS
    try:
        value = int(raw)
    except ValueError:
        logger.warning(
            "Invalid %s; falling back to default",
            NOTIFY_RETENTION_ENV,
            extra={"value": raw, "default": DEFAULT_RETENTION_DAYS},
        )
        return DEFAULT_RETENTION_DAYS
    return value if value > 0 else None


async def remind_once(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    now: datetime,
    cutover: datetime | None,
    interval: timedelta,
) -> int:
    """One sweep. Returns how many reminder rows went in."""
    async with session_factory() as session:
        item_ids = await _checked_items_in_error(session)
    inserted = 0
    for item_id in item_ids:
        inserted += await _remind_item(
            session_factory, item_id, now=now, cutover=cutover, interval=interval
        )
    return inserted


async def _checked_items_in_error(session: AsyncSession) -> list[ULID]:
    """Items cached in error that Watcher still checks: the announced ``active`` isn't false."""
    rows = await session.execute(
        select(InfoItem, Domain)
        .join(WatchStatus, WatchStatus.info_item_id == InfoItem.info_item_id)
        .outerjoin(
            InfoItemSource,
            (InfoItemSource.info_item_id == InfoItem.info_item_id)
            & InfoItemSource.deactivated_at.is_(None),
        )
        .outerjoin(InfoSource, InfoSource.info_source_id == InfoItemSource.info_source_id)
        .outerjoin(Domain, Domain.name == InfoSource.domain_name)
        .where(WatchStatus.health == "error")
        .order_by(InfoItem.info_item_id)
    )
    return [
        item.info_item_id
        for item, domain in rows.all()
        if resolved_active(
            item.watch_active,
            archived=item.archived_at is not None,
            host_suspended=domain_suspended(domain),
        )
        is not False
    ]


async def _remind_item(
    session_factory: async_sessionmaker[AsyncSession],
    item_id: ULID,
    *,
    now: datetime,
    cutover: datetime | None,
    interval: timedelta,
) -> int:
    async with session_factory() as session:
        episode = await _open_episode(session, item_id)
        if episode is None:
            logger.info(
                "item in error has no episode row; no reminder",
                extra={"info_item_id": str(item_id)},
            )
            return 0
        item = await load_item_facts(session, item_id)
        due: list[tuple[SubscriptionMatch, int, datetime]] = []
        for sub in await subscriptions_for(session, item_id, "watch_error"):
            last = await _last_notified(session, sub.id, episode.event_id)
            if last is None:
                continue  # it never heard this episode
            reminded, notified_at = last
            if now - notified_at >= interval:
                match = SubscriptionMatch(
                    sub.id,
                    sub.remote_channel_id,
                    resolve_options(sub.content_config, "watch_error"),
                )
                due.append((match, reminded + 1, notified_at))
    if item is None or not due:
        return 0

    edge = WatchErrorEvent.model_validate(episode.fact)
    as_reminder = edge.model_copy(update={"occurred_at": now})
    rows = [
        PlannedRow(
            subscription_id=match.subscription_id,
            remote_channel_id=match.remote_channel_id,
            idempotency_key=reminder_key(match.subscription_id, edge.event_id, n),
            reminder=n,
            reminded_at=now,
            **await compose_row(
                as_reminder, item, match, diff=None, previously_notified_at=last_at
            ),
        )
        for match, n, last_at in due
    ]
    async with session_factory() as session:
        inserted = await insert_rows(session, edge, rows, mode=mode_for(now, cutover))
        await session.commit()
    if inserted:
        logger.info(
            "error reminders recorded",
            extra={"info_item_id": str(item_id), "event_id": edge.event_id, "rows": inserted},
        )
    return inserted


async def _open_episode(session: AsyncSession, item_id: ULID) -> NotificationDispatch | None:
    """The newest ``watch_error`` row for the item, unless a recovery came after it."""
    newest = await session.scalar(
        select(NotificationDispatch)
        .where(
            NotificationDispatch.info_item_id == item_id,
            NotificationDispatch.event_type == "watch_error",
        )
        .order_by(NotificationDispatch.occurred_at.desc(), NotificationDispatch.id.desc())
        .limit(1)
    )
    if newest is None:
        return None
    recovered = await session.scalar(
        select(func.count())
        .select_from(NotificationDispatch)
        .where(
            NotificationDispatch.info_item_id == item_id,
            NotificationDispatch.event_type == "watch_recovered",
            NotificationDispatch.occurred_at > newest.occurred_at,
        )
    )
    return None if recovered else newest


async def _last_notified(
    session: AsyncSession, subscription_id: ULID, episode_event_id: str
) -> tuple[int, datetime] | None:
    """The subscription's newest reminder ordinal in the episode, and when it was told."""
    row = (
        await session.execute(
            select(
                func.max(NotificationDispatch.reminder),
                func.max(
                    func.coalesce(
                        NotificationDispatch.reminded_at, NotificationDispatch.occurred_at
                    )
                ),
            ).where(
                NotificationDispatch.subscription_id == subscription_id,
                NotificationDispatch.event_id == episode_event_id,
            )
        )
    ).one()
    return None if row[0] is None else (row[0], row[1])


async def prune_dispatches(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    retention_days: int | None,
    now: datetime,
) -> int:
    """Delete terminal rows created before the window, in bounded batches. Returns how many."""
    if retention_days is None:
        return 0
    cutoff = now - timedelta(days=retention_days)
    deleted = 0
    for _ in range(MAX_PRUNE_BATCHES):
        async with session_factory() as session:
            doomed = (
                select(NotificationDispatch.id)
                .where(
                    NotificationDispatch.created_at < cutoff,
                    NotificationDispatch.status.in_(TERMINAL_STATUSES),
                )
                .order_by(NotificationDispatch.created_at, NotificationDispatch.id)
                .limit(PRUNE_BATCH_SIZE)
            )
            result = await session.execute(
                delete(NotificationDispatch)
                .where(NotificationDispatch.id.in_(doomed))
                .execution_options(synchronize_session=False)
            )
            await session.commit()
        deleted += result.rowcount
        if result.rowcount < PRUNE_BATCH_SIZE:
            break
    if deleted:
        logger.info(
            "Notification dispatches pruned",
            extra={"deleted": deleted, "retention_days": retention_days},
        )
    return deleted


async def run(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    stop_event: asyncio.Event,
    cutover: datetime | None,
    interval: timedelta = DEFAULT_RENOTIFY_INTERVAL,
    retention_days: int | None = DEFAULT_RETENTION_DAYS,
    timer_seconds: float = TIMER_SECONDS,
    error_backoff_base: float = ERROR_BACKOFF_BASE_SECONDS,
) -> None:
    """Remind and prune every ``timer_seconds`` until ``stop_event`` is set; once at startup."""
    logger.info(
        "Error reminder timer starting",
        extra={
            "timer_seconds": timer_seconds,
            "interval_hours": interval / timedelta(hours=1),
            "retention_days": retention_days,
        },
    )
    consecutive_failures = 0
    while not stop_event.is_set():
        try:
            now = datetime.now(UTC)
            await remind_once(session_factory, now=now, cutover=cutover, interval=interval)
            await prune_dispatches(session_factory, retention_days=retention_days, now=now)
            consecutive_failures = 0
            delay = timer_seconds
        except asyncio.CancelledError:
            raise
        except Exception:
            consecutive_failures += 1
            logger.exception(
                "Error reminder sweep failed; backing off",
                extra={"consecutive_failures": consecutive_failures},
            )
            delay = error_backoff_seconds(consecutive_failures, error_backoff_base)
        await asyncio.wait(
            [asyncio.create_task(stop_event.wait())],
            timeout=delay,
            return_when=asyncio.FIRST_COMPLETED,
        )
