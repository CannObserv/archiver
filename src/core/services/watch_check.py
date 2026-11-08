"""Check-now: the ``info.watch-check`` command and the state it reads back (archiver#370).

The operator asks Watcher to check an item now. Archiver outboxes a
``WatchCheckCommand`` (a forced full fetch, co-core 0.38) beside a
``watch_check_commands`` row, in one transaction. There is no ack path: the
outcome is a level on ``info.watch-status`` (``last_full_fetch_at`` passing
``requested_at``, plus ``health``), or a ``check_rejected`` fact on
``info.watch-events`` correlated by ``command_id``.

**The state ladder** (D2), first match wins:

1. a rejection is recorded → ``rejected``, the reason verbatim;
2. ``last_full_fetch_at > requested_at`` → ``done``, plus ``health`` and
   ``health_reason`` (a 200 whose extraction then failed is done + error);
3. older than the timeout → ``no_answer``;
4. otherwise ``pending``.

A scheduled fetch that lands after ``requested_at`` also completes the check.
That is correct: the content is fresh, whoever asked. The two clocks differ
(``requested_at`` is Archiver's, ``last_full_fetch_at`` Watcher's) and no
slack is added.

**No answer is not a verdict** (D5). A dead-lettered command
(``info.watch-check.dlq``) gets no answer at all, and a down Watcher answers on
its return. So does a fetch Replicator has not answered: Watcher reaps it only
after 1800 s and errors the item only after 3 re-issues, about 2 h, and
re-issues publish nothing. The default 15 min therefore reaches all three; a
later completion still flips the state to done.

**One open command per item** (D4): only ``pending`` is open. A click while one
is pending is refused here, rather than sent for Watcher to reject as
``fetch_open``. After done, rejected or no answer, a click mints a fresh
``command_id`` and ``requested_at``.

**Off unless switched on** (D6). ``ARCHIVER_WATCH_CHECK_ENABLED`` is flip F4: set
only in ``deploy/archiver.service``, never in an env file. Off, nothing is
enqueued; the dashboard hides the button and its routes 404.

**Never capped.** ``info.watch-check`` is a command stream: it stays out of the
publisher's ``trim_topics`` and ``topic_maxlen`` (CannObserv/broker STREAMS.md:
"never XTRIMmed"). Archiver's ``+xadd`` would admit ``XADD … MAXLEN``, so only
the code prevents it.
"""

from __future__ import annotations

import math
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from co_core.pure.adapters.bus.streams import INFO_WATCH_CHECK
from co_core.pure.models.changes import CheckRejectedEvent, WatchCheckCommandEmit
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.core.logging import get_logger
from src.core.models import ChangesOutboxRow, InfoItem, WatchCheckCommand, WatchStatus

logger = get_logger(__name__)

WATCH_CHECK_TOPIC = INFO_WATCH_CHECK

ENABLED_ENV = "ARCHIVER_WATCH_CHECK_ENABLED"
"""The F4 switch. Set only in ``deploy/archiver.service``; never in an env file."""

TIMEOUT_ENV = "ARCHIVER_WATCH_CHECK_TIMEOUT_SECONDS"
DEFAULT_TIMEOUT = timedelta(minutes=15)

_TRUTHY = frozenset({"1", "true", "yes", "on"})

CheckKind = Literal["pending", "done", "rejected", "no_answer"]
RejectionDisposition = Literal["recorded", "duplicate", "unknown_command"]


class CheckNowDisabled(RuntimeError):
    """The F4 switch is off: nothing may be enqueued."""


class CheckAlreadyOpen(RuntimeError):
    """The item's latest command is still pending (D4)."""


def check_enabled(environ: Mapping[str, str] = os.environ) -> bool:
    """Whether check-now is on. Read per call, so a test flips it without a reload."""
    return (environ.get(ENABLED_ENV) or "").strip().lower() in _TRUTHY


def check_timeout(environ: Mapping[str, str] = os.environ) -> timedelta:
    """The no-answer horizon; malformed, non-finite or non-positive → the default."""
    raw = (environ.get(TIMEOUT_ENV) or "").strip()
    try:
        seconds = float(raw)
    except ValueError:
        return DEFAULT_TIMEOUT
    if not math.isfinite(seconds) or seconds <= 0:
        return DEFAULT_TIMEOUT
    return timedelta(seconds=seconds)


@dataclass(frozen=True, slots=True)
class CheckState:
    """Where one command stands, derived at read time."""

    kind: CheckKind
    command_id: str
    requested_at: datetime
    reason: str | None = None
    completed_at: datetime | None = None
    health: str | None = None
    health_reason: str | None = None
    health_status_code: int | None = None

    @property
    def open(self) -> bool:
        """Only a pending command blocks a new click (D4)."""
        return self.kind == "pending"

    @property
    def health_ok(self) -> bool:
        """``"ok"`` is the only healthy value; anything else renders as not."""
        return self.health == "ok"


def check_state(
    command: WatchCheckCommand,
    status: WatchStatus | None,
    *,
    now: datetime,
    timeout: timedelta = DEFAULT_TIMEOUT,
) -> CheckState:
    """D2's ladder: rejected → done → no answer → pending."""
    base = {"command_id": command.command_id, "requested_at": command.requested_at}
    if command.rejected_reason is not None:
        return CheckState(kind="rejected", reason=command.rejected_reason, **base)
    fetched = status.last_full_fetch_at if status is not None else None
    if fetched is not None and fetched > command.requested_at:
        return CheckState(
            kind="done",
            completed_at=fetched,
            health=status.health,
            health_reason=status.health_reason,
            health_status_code=status.health_status_code,
            **base,
        )
    if now - command.requested_at > timeout:
        return CheckState(kind="no_answer", **base)
    return CheckState(kind="pending", **base)


async def latest_check(session: AsyncSession, info_item_id: ULID) -> WatchCheckCommand | None:
    """The item's newest command, or ``None`` if it has never been checked."""
    return (
        await session.execute(
            select(WatchCheckCommand)
            .where(WatchCheckCommand.info_item_id == info_item_id)
            .order_by(WatchCheckCommand.requested_at.desc(), WatchCheckCommand.command_id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def current_state(
    session: AsyncSession,
    info_item_id: ULID,
    *,
    now: datetime,
    timeout: timedelta = DEFAULT_TIMEOUT,
) -> CheckState | None:
    """The item's latest command's state, or ``None`` if it has never been checked."""
    command = await latest_check(session, info_item_id)
    if command is None:
        return None
    status = await session.get(WatchStatus, info_item_id, populate_existing=True)
    return check_state(command, status, now=now, timeout=timeout)


async def request_check(
    session: AsyncSession,
    info_item_id: ULID,
    *,
    requested_by: ULID | None,
    environ: Mapping[str, str] = os.environ,
) -> WatchCheckCommand:
    """Outbox one ``WatchCheckCommand`` for the item. Caller commits.

    Locks the item row so two concurrent clicks cannot both pass the
    one-open-command check. Raises :class:`CheckNowDisabled` with the switch off
    and :class:`CheckAlreadyOpen` while the latest command is pending; neither
    writes anything.
    """
    if not check_enabled(environ):
        raise CheckNowDisabled(f"{ENABLED_ENV} is not set")
    await session.execute(
        select(InfoItem.info_item_id).where(InfoItem.info_item_id == info_item_id).with_for_update()
    )
    now = datetime.now(UTC)
    state = await current_state(session, info_item_id, now=now, timeout=check_timeout(environ))
    if state is not None and state.open:
        raise CheckAlreadyOpen(f"check {state.command_id} is still pending")

    command_id = str(ULID())
    emit = WatchCheckCommandEmit(
        occurred_at=now,
        command_id=command_id,
        info_item_id=str(info_item_id),
        requested_at=now,
    )
    row = WatchCheckCommand(
        command_id=command_id,
        info_item_id=info_item_id,
        requested_at=now,
        requested_by=requested_by,
    )
    session.add(row)
    session.add(ChangesOutboxRow(topic=WATCH_CHECK_TOPIC, payload=emit.model_dump(mode="json")))
    logger.info(
        "Watch check requested",
        extra={"command_id": command_id, "info_item_id": str(info_item_id)},
    )
    return row


async def record_rejection(session: AsyncSession, fact: CheckRejectedEvent) -> RejectionDisposition:
    """Close a command with Watcher's rejection. Caller commits. First write wins.

    ``recorded``: stored. ``duplicate``: already rejected (a redelivered command
    can mint a second ``event_id``). ``unknown_command``: no such command - only
    Archiver issues them, so the caller logs it as a fault.
    """
    result = await session.execute(
        update(WatchCheckCommand)
        .where(
            WatchCheckCommand.command_id == fact.command_id,
            WatchCheckCommand.rejected_reason.is_(None),
        )
        .values(rejected_reason=fact.reason, rejected_at=fact.occurred_at)
    )
    if result.rowcount:
        return "recorded"
    exists = (
        await session.execute(
            select(WatchCheckCommand.command_id).where(
                WatchCheckCommand.command_id == fact.command_id
            )
        )
    ).scalar_one_or_none()
    return "duplicate" if exists is not None else "unknown_command"
