"""Viewport capture: issue ``content.capture``, apply its outcomes (archiver#380 slice A).

Archiver records the policy and issues the command; Replicator renders the page
in a confined headless browser, stores the PNG in its temporary store, and
answers on ``content.artifacts`` with ``capture_stored`` or ``capture_failed``.
The normative obligations are Replicator's ``content-capture-issuer-contract.md``
(C1-C5); the wire models are co-core's (cannobserv#571).

**Slice A is on demand only.** An operator clicks "Capture now" on InfoSource
detail and one command goes out with the fixed default profile
(``DEFAULT_VIEWPORT``, ``DEFAULT_FULL_PAGE``, no wait). The per-source policy
and the per-revision trigger are slice C; keeping a capture past
``blob_expires_at`` (``content.persist``) is slice B.

**Off unless switched on.** ``ARCHIVER_CAPTURE_ENABLED`` is set only in
``deploy/archiver.service``, never in an env file. Off, nothing is enqueued and
the dashboard hides the button. Replicator created ``replicator.capture`` at
``0`` before Archiver's first write (C5, CannObserv/broker#116).

**One open command per source.** A click while the source's latest command is
``requested`` is refused here rather than sent: each render is a whole browser
launch, paced per host.

**Outcomes** (``apply_capture_stored`` / ``apply_capture_failed``), correlated on
``command_id`` alone:

- **The first success is kept (C1).** Delivery is at-least-once and a
  redelivery past Replicator's dedupe window renders again, usually under
  another digest. Either is a true capture; the first stays, so a later persist
  (slice B) names one stable object.
- **A success outranks a failure or an abandon.** An image exists once any fact
  says so.
- **``terminal`` first, then ``reason`` opaque (C2).** A non-terminal failure is
  recorded and the command stays open. ``wait_timeout`` is terminal: the remedy
  is another condition under a fresh ``command_id``, which is a person's call in
  slice A.
- **An unknown ``command_id``** raises ``UnknownCommandError``, which the
  consumer acks and drops, as for replicate and persist.

**The reaper abandons and re-issues nothing** (``reap_open_captures``). Silence
means "still trying" or "lost" (C2); past ``DEFAULT_REAP_HORIZON`` the command
closes ``abandoned`` and the button is live again. Re-issuing is a person's in
slice A; the capped automatic re-issue arrives with slice C's unattended
triggers.

**Never capped.** ``content.capture`` is a command stream: it stays out of the
publisher's ``trim_topics`` (CannObserv/broker STREAMS.md: "never XTRIMmed").

Nothing here commits: the caller owns the transaction, so the command row and
its outbox row land together.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

from co_core.pure.adapters.bus.streams import CONTENT_CAPTURE
from co_core.pure.models.changes import (
    CaptureFailedEvent,
    CaptureStoredEvent,
    CaptureViewportEmit,
    ContentCaptureCommandEmit,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.core.logging import get_logger
from src.core.models import CaptureCommand, ChangesOutboxRow, InfoSource
from src.core.services.replication_writeback import UnknownCommandError

logger = get_logger(__name__)

CAPTURE_TOPIC = CONTENT_CAPTURE

ENABLED_ENV = "ARCHIVER_CAPTURE_ENABLED"
"""Set only in ``deploy/archiver.service``; never in an env file."""

_TRUTHY = frozenset({"1", "true", "yes", "on"})

# The one profile slice A sends. A common desktop viewport, the whole page:
# Replicator refuses (``too_large``) rather than clips past 4096 x 32768 px.
DEFAULT_VIEWPORT = (1280, 800)
DEFAULT_FULL_PAGE = True

# A render is bounded by Replicator's 120 s fetch deadline and paced per host;
# a 5xx on the navigation is retried with no fact. An hour is many retries.
DEFAULT_REAP_HORIZON = timedelta(hours=1)

STATE_REQUESTED = "requested"
STATE_STORED = "stored"
STATE_FAILED = "failed"
STATE_ABANDONED = "abandoned"

# The reaper's local reason, persist's and replication's token for the same thing.
REASON_NO_FACT = "no_fact_before_horizon"


class CaptureDisabled(RuntimeError):
    """``ARCHIVER_CAPTURE_ENABLED`` is off: nothing may be enqueued."""


class CaptureAlreadyOpen(RuntimeError):
    """The source's latest command is still ``requested``."""


def capture_enabled(environ: Mapping[str, str] = os.environ) -> bool:
    """Whether capture is on. Read per call, so a test flips it without a reload."""
    return (environ.get(ENABLED_ENV) or "").strip().lower() in _TRUTHY


async def latest_capture(session: AsyncSession, info_source_id: ULID) -> CaptureCommand | None:
    """The source's newest command, or ``None`` if it has never been captured."""
    return (
        await session.execute(
            select(CaptureCommand)
            .where(CaptureCommand.info_source_id == info_source_id)
            .order_by(CaptureCommand.issued_at.desc(), CaptureCommand.command_id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def request_capture(
    session: AsyncSession,
    info_source_id: ULID,
    *,
    requested_by: ULID | None,
    environ: Mapping[str, str] = os.environ,
) -> CaptureCommand:
    """Outbox one ``ContentCaptureCommand`` for the source. Caller commits.

    Locks the source row so two concurrent clicks cannot both pass the
    one-open-command check. Raises :class:`CaptureDisabled` with the switch off,
    :class:`LookupError` for an unknown source, and :class:`CaptureAlreadyOpen`
    while the latest command is open; none writes anything.
    """
    if not capture_enabled(environ):
        raise CaptureDisabled(f"{ENABLED_ENV} is not set")
    source = (
        await session.execute(
            select(InfoSource).where(InfoSource.info_source_id == info_source_id).with_for_update()
        )
    ).scalar_one_or_none()
    if source is None:
        raise LookupError(f"no InfoSource {info_source_id}")
    latest = await latest_capture(session, info_source_id)
    if latest is not None and latest.state == STATE_REQUESTED:
        raise CaptureAlreadyOpen(f"capture {latest.command_id} is still open")

    now = datetime.now(UTC)
    command_id = str(ULID())
    width, height = DEFAULT_VIEWPORT
    emit = ContentCaptureCommandEmit(
        occurred_at=now,
        command_id=command_id,
        url=source.url,
        info_source_id=str(info_source_id),
        viewport=CaptureViewportEmit(width=width, height=height),
        full_page=DEFAULT_FULL_PAGE,
        wait=None,
    )
    command = CaptureCommand(
        command_id=command_id,
        info_source_id=info_source_id,
        url=source.url,
        viewport_width=width,
        viewport_height=height,
        full_page=DEFAULT_FULL_PAGE,
        wait=None,
        requested_by=requested_by,
        issued_at=now,
        state=STATE_REQUESTED,
    )
    session.add(command)
    session.add(ChangesOutboxRow(topic=CAPTURE_TOPIC, payload=emit.model_dump(mode="json")))
    logger.info(
        "Capture requested",
        extra={"command_id": command_id, "info_source_id": str(info_source_id)},
    )
    return command


async def apply_capture_stored(session: AsyncSession, fact: CaptureStoredEvent) -> CaptureCommand:
    """Record ``capture_stored``. The first success is kept (C1). Does not commit.

    Raises:
        UnknownCommandError: the registry never issued this command.
    """
    command = await _load(session, fact.command_id)
    if command.state == STATE_STORED:
        logger.info(
            "Redelivered capture success; keeping the first",
            extra={
                "command_id": fact.command_id,
                "kept_fingerprint": command.content_fingerprint,
                "fact_fingerprint": fact.content_fingerprint,
                "occurred_at": fact.occurred_at.isoformat(),
            },
        )
        return command

    command.content_fingerprint = fact.content_fingerprint
    command.blob_uri = fact.blob_uri
    command.media_type = fact.media_type
    command.size_bytes = fact.size_bytes
    command.image_width = fact.image_width
    command.image_height = fact.image_height
    command.final_url = fact.final_url
    command.captured_at = fact.captured_at
    command.blob_expires_at = fact.blob_expires_at
    command.reason = None
    command.detail = None
    command.status_code = None
    _close(command, STATE_STORED, fact.occurred_at)
    logger.info(
        "Capture stored",
        extra={
            "command_id": fact.command_id,
            "info_source_id": str(command.info_source_id),
            "content_fingerprint": fact.content_fingerprint,
            "size_bytes": fact.size_bytes,
            "image_width": fact.image_width,
            "image_height": fact.image_height,
            "blob_expires_at": fact.blob_expires_at.isoformat() if fact.blob_expires_at else None,
        },
    )
    return command


async def apply_capture_failed(session: AsyncSession, fact: CaptureFailedEvent) -> CaptureCommand:
    """Record ``capture_failed``; close the command only when ``terminal``.

    Never overrides a success, and never lets an older fact override a newer
    one. A non-terminal fact applies only to an open command; a terminal one
    also closes an abandoned command ``failed``, Replicator's verdict being more
    specific than the reaper's. Does not commit.

    Raises:
        UnknownCommandError: the registry never issued this command.
    """
    command = await _load(session, fact.command_id)
    if command.state == STATE_STORED:
        logger.warning(
            "Ignoring a failure fact for an already-stored capture",
            extra={"command_id": fact.command_id, "reason": fact.reason},
        )
        return command
    if not fact.terminal and command.state != STATE_REQUESTED:
        # A still-trying fact says nothing about a closed command: it must not
        # rewrite the verdict (an abandon's reason) or mark it non-terminal.
        logger.info(
            "Ignoring a non-terminal capture fact for a closed command",
            extra={"command_id": fact.command_id, "state": command.state, "reason": fact.reason},
        )
        return command
    if command.last_fact_at is not None and fact.occurred_at < command.last_fact_at:
        logger.info(
            "Ignoring a capture fact older than one already applied",
            extra={
                "command_id": fact.command_id,
                "occurred_at": fact.occurred_at.isoformat(),
                "last_fact_at": command.last_fact_at.isoformat(),
            },
        )
        return command

    command.reason = fact.reason
    command.detail = fact.detail
    command.status_code = fact.status_code
    command.terminal = fact.terminal
    command.last_fact_at = fact.occurred_at
    if fact.terminal:
        _close(command, STATE_FAILED, fact.occurred_at)

    logger.log(
        logging.WARNING if fact.terminal else logging.INFO,
        "Capture failed" if fact.terminal else "Capture attempt failed; still retrying",
        extra={
            "command_id": fact.command_id,
            "info_source_id": str(command.info_source_id),
            "reason": fact.reason,
            "terminal": fact.terminal,
            "status_code": fact.status_code,
        },
    )
    return command


async def reap_open_captures(
    session: AsyncSession, *, horizon: timedelta = DEFAULT_REAP_HORIZON
) -> int:
    """Abandon commands open past ``horizon``. Returns how many. Re-issues nothing.

    Does not commit.
    """
    cutoff = datetime.now(UTC) - horizon
    stale = list(
        (
            await session.execute(
                select(CaptureCommand)
                .where(
                    CaptureCommand.state == STATE_REQUESTED,
                    CaptureCommand.closed_at.is_(None),
                    CaptureCommand.issued_at <= cutoff,
                )
                .order_by(CaptureCommand.issued_at, CaptureCommand.command_id)
            )
        )
        .scalars()
        .all()
    )
    now = datetime.now(UTC)
    for command in stale:
        command.state = STATE_ABANDONED
        command.reason = REASON_NO_FACT
        command.closed_at = now
        logger.warning(
            "Capture command produced no fact before the horizon; abandoning",
            extra={
                "command_id": command.command_id,
                "info_source_id": str(command.info_source_id),
                "issued_at": command.issued_at.isoformat(),
                "horizon_hours": horizon.total_seconds() / 3600,
            },
        )
    await session.flush()
    return len(stale)


async def _load(session: AsyncSession, command_id: str) -> CaptureCommand:
    command = await session.get(CaptureCommand, command_id)
    if command is None:
        raise UnknownCommandError(command_id)
    return command


def _close(command: CaptureCommand, state: str, occurred_at: datetime) -> None:
    command.state = state
    command.terminal = True
    # A high-water mark: a late success must not wind it back.
    if command.last_fact_at is None or occurred_at > command.last_fact_at:
        command.last_fact_at = occurred_at
    if command.closed_at is None:
        command.closed_at = datetime.now(UTC)
