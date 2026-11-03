"""The drain: pending notification rows to Notifier, oldest first (archiver#369, D4).

A lifespan task that runs only where the Notifier gate is open. With T unset
nothing is ever ``pending`` (D3), so it idles. Per row, in its own transaction:

1. **Claim** the oldest due ``pending`` row ``FOR UPDATE SKIP LOCKED``. The
   lock is held across the call, so a second drain can't send it twice.
2. **Skip** a row whose subscription was deleted (the ref went ``NULL``) or is
   now inactive: deactivating is the operator's brake on a queue already built.
3. **Send** through ``Notifier.dispatch_composed``, the one send, with the row's
   idempotency key.
4. **Settle.** Any ``DispatchOut`` is terminal: ``succeeded`` → ``sent``,
   anything else → ``failed`` with Notifier's reason. Notifier's key is
   permanent per tenant, so re-POSTing returns the failed record, and a retry
   loop would spin. **Nothing redelivers** (#367's boundary test bans it).
   A retryable :class:`NotifierUnavailable` (a timeout is "unknown", not
   "failed") keeps the row ``pending`` under the same key, backed off, until
   :data:`MAX_ATTEMPTS` ends it ``failed`` with the last reason. A refusal fails
   it at once. A row is never dropped.

One INFO line per settled row: ids and outcome, never the text or the key.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Protocol

from sqlalchemy import or_, select

from src.core.changes.backoff import (
    ERROR_BACKOFF_BASE_SECONDS,
    ERROR_LOG_EVERY,
    error_backoff_seconds,
)
from src.core.logging import get_logger
from src.core.models import NotificationDispatch, NotificationSubscription
from src.core.notifier.client import Dispatched, NotifierUnavailable

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = get_logger(__name__)

#: A row's attempts before it ends ``failed`` with the last reason.
MAX_ATTEMPTS = 8
#: The first retry's delay; each later one doubles, up to :data:`MAX_BACKOFF`.
FIRST_BACKOFF = timedelta(seconds=30)
MAX_BACKOFF = timedelta(hours=1)
#: Rows settled per pass before the loop looks at the stop event again.
CLAIM_BATCH = 10
#: How long an idle drain waits before it looks again.
POLL_SECONDS = 10.0


class Dispatcher(Protocol):
    """The slice of ``Notifier`` the drain uses."""

    async def dispatch_composed(
        self,
        *,
        channel_id: str,
        title: str,
        body: str,
        idempotency_key: str,
        metadata: dict[str, object],
    ) -> Dispatched: ...


def backoff(attempts: int) -> timedelta:
    """The wait after the ``attempts``-th failed try: 30 s, doubling, capped at 1 h."""
    doublings = min(max(attempts - 1, 0), 16)  # 2**16 * 30 s is far past the cap
    return min(FIRST_BACKOFF * 2**doublings, MAX_BACKOFF)


async def drain_once(
    session_factory: async_sessionmaker[AsyncSession],
    notifier: Dispatcher,
    *,
    now: datetime | None = None,
    batch: int = CLAIM_BATCH,
) -> int:
    """Settle up to ``batch`` due rows, one transaction each. Returns how many."""
    settled = 0
    for _ in range(batch):
        async with session_factory() as session:
            row = await _claim(session, now or datetime.now(UTC))
            if row is None:
                break
            await _settle(session, row, notifier, now or datetime.now(UTC))
            await session.commit()
        settled += 1
    return settled


async def _claim(session: AsyncSession, now: datetime) -> NotificationDispatch | None:
    return await session.scalar(
        select(NotificationDispatch)
        .where(
            NotificationDispatch.status == "pending",
            or_(
                NotificationDispatch.next_attempt_at.is_(None),
                NotificationDispatch.next_attempt_at <= now,
            ),
        )
        .order_by(NotificationDispatch.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )


async def _settle(
    session: AsyncSession, row: NotificationDispatch, notifier: Dispatcher, now: datetime
) -> None:
    skip = await _skip_reason(session, row)
    if skip is not None:
        _finish(row, "skipped", skip)
        return
    row.attempts += 1
    try:
        dispatched = await notifier.dispatch_composed(
            channel_id=row.remote_channel_id,
            title=row.title,
            body=row.body,
            idempotency_key=row.idempotency_key,
            metadata={
                "event_type": row.event_type,
                "event_id": row.event_id,
                "info_item_id": str(row.info_item_id),
                "subscription_id": str(row.subscription_id),
                "reminder": row.reminder,
            },
        )
    except NotifierUnavailable as e:
        _retry_or_fail(row, str(e), retryable=e.retryable, now=now)
        return
    except Exception as e:
        # Not translated by the adapter: still an attempt, and retryable under
        # the same key, so the row backs off instead of holding the head of the
        # queue on every pass (CR 3). By type only: the text may quote anything.
        logger.warning(
            "notification dispatch raised an untranslated error",
            extra={"dispatch_row_id": str(row.id), "error_type": type(e).__name__},
            exc_info=True,
        )
        _retry_or_fail(row, f"unexpected error ({type(e).__name__})", retryable=True, now=now)
        return
    row.notifier_dispatch_id = dispatched.id
    if dispatched.status == "succeeded":
        _finish(row, "sent", None)
    else:
        _finish(row, "failed", dispatched.reason or f"delivery {dispatched.status}")


def _retry_or_fail(
    row: NotificationDispatch, reason: str, *, retryable: bool, now: datetime
) -> None:
    """Back off under the same key, or end ``failed`` once refused or capped."""
    if retryable and row.attempts < MAX_ATTEMPTS:
        row.reason = reason
        row.next_attempt_at = now + backoff(row.attempts)
        _log(row, "retrying")
    else:
        _finish(row, "failed", reason)


async def _skip_reason(session: AsyncSession, row: NotificationDispatch) -> str | None:
    if row.subscription_id is None:
        return "subscription deleted"
    active = await session.scalar(
        select(NotificationSubscription.is_active).where(
            NotificationSubscription.id == row.subscription_id
        )
    )
    if active is None:
        return "subscription deleted"
    return None if active else "subscription inactive"


def _finish(row: NotificationDispatch, status: str, reason: str | None) -> None:
    row.status = status
    row.reason = reason
    row.next_attempt_at = None
    _log(row, status)


def _log(row: NotificationDispatch, outcome: str) -> None:
    logger.info(
        "notification dispatch %s",
        outcome,
        extra={
            "dispatch_row_id": str(row.id),
            "event_id": row.event_id,
            "event_type": row.event_type,
            "reminder": row.reminder,
            "subscription_id": str(row.subscription_id) if row.subscription_id else None,
            "channel_id": row.remote_channel_id,
            "notifier_dispatch_id": row.notifier_dispatch_id,
            "attempts": row.attempts,
            "reason": row.reason,
        },
    )


async def run(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    notifier: Dispatcher,
    stop_event: asyncio.Event,
    poll_seconds: float = POLL_SECONDS,
    error_backoff_base: float = ERROR_BACKOFF_BASE_SECONDS,
) -> None:
    """Drain until ``stop_event`` is set. A full batch loops at once; otherwise it polls."""
    logger.info("Notification drain starting", extra={"poll_seconds": poll_seconds})
    consecutive_failures = 0
    while not stop_event.is_set():
        try:
            settled = await drain_once(session_factory, notifier)
            consecutive_failures = 0
            if settled == CLAIM_BATCH:
                continue
            delay = poll_seconds
        except asyncio.CancelledError:
            raise
        except Exception:
            consecutive_failures += 1
            if consecutive_failures == 1 or consecutive_failures % ERROR_LOG_EVERY == 0:
                logger.exception(
                    "Notification drain failed; backing off",
                    extra={"consecutive_failures": consecutive_failures},
                )
            delay = error_backoff_seconds(consecutive_failures, error_backoff_base)
        await asyncio.wait(
            [asyncio.create_task(stop_event.wait())],
            timeout=delay,
            return_when=asyncio.FIRST_COMPLETED,
        )
