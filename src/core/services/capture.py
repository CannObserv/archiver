"""Viewport capture: issue ``content.capture``, apply its outcomes (archiver#380).

Archiver records the policy and issues the command; Replicator renders the page
in a confined headless browser, stores the PNG in its temporary store, and
answers on ``content.artifacts`` with ``capture_stored`` or ``capture_failed``.
The normative obligations are Replicator's ``content-capture-issuer-contract.md``
(C1-C5); the wire models are co-core's (cannobserv#571).

**Three occasions, one shape.** Every command sends the source's capture policy
(``info_sources.capture_policy``, ``src.core.capture_policy``; slice C), or
``DEFAULT_POLICY`` where it has none:

- **On demand:** an operator clicks "Capture now" on InfoSource detail
  (``request_capture``).
- **On a new revision**, for a source whose policy opts in (``on_revision``,
  D3; ``capture_for_revision``, called by ``record_revision``). The command
  names the revision, but the link is temporal: it renders the live page.
- **Re-issue:** the reaper re-sends a silent command, capped (below).

Keeping a capture past ``blob_expires_at`` is slice B: applying
``capture_stored`` issues a ``content.persist`` for the image
(``persist_issuance.issue_capture_persist``, under ``ARCHIVER_PERSIST_ISSUANCE``),
and the reaper's catch-up re-issues one that was lost, failed or never sent.

**Off unless switched on.** ``ARCHIVER_CAPTURE_ENABLED`` is set only in
``deploy/archiver.service``, never in an env file. Off, nothing is enqueued and
the dashboard hides the button. Replicator created ``replicator.capture`` at
``0`` before Archiver's first write (C5, CannObserv/broker#116).

**One open command per source.** A click while the source's latest command is
``requested`` is refused here rather than sent: each render is a whole browser
launch, paced per host. A revision arriving while one is open issues nothing:
the open command renders the live page anyway.

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
  is another condition under a fresh ``command_id``, a person's call (edit the
  policy, capture again). A terminal failure is never re-issued automatically.
- **An unknown ``command_id``** raises ``UnknownCommandError``, which the
  consumer acks and drops, as for replicate and persist.

**The reaper abandons, then re-issues, capped** (``reap_open_captures``).
Silence means "still trying" or "lost" (C2); past ``DEFAULT_REAP_HORIZON`` the
command closes ``abandoned`` and a fresh one goes out under a new
``command_id`` with exactly what the silent one sent (``reissue_of``,
``attempt + 1``), up to ``MAX_CAPTURE_REISSUES`` times. Every occasion is
re-issued, a click's included: the person who asked for a capture still wants
one. Not re-issued: with the switch off, or once the source has a newer command.

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
from typing import Any, NamedTuple

from co_core.pure.adapters.bus.streams import CONTENT_CAPTURE
from co_core.pure.models.changes import (
    CaptureFailedEvent,
    CaptureStoredEvent,
    CaptureViewportEmit,
    ContentCaptureCommandEmit,
)
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.core.capture_policy import DEFAULT_POLICY, CapturePolicy, effective_policy
from src.core.logging import get_logger
from src.core.models import CaptureCommand, ChangesOutboxRow, InfoSource, SourceRevision
from src.core.services.persist_issuance import issue_capture_persist
from src.core.services.replication_writeback import UnknownCommandError

logger = get_logger(__name__)

CAPTURE_TOPIC = CONTENT_CAPTURE

ENABLED_ENV = "ARCHIVER_CAPTURE_ENABLED"
"""Set only in ``deploy/archiver.service``; never in an env file."""

_TRUTHY = frozenset({"1", "true", "yes", "on"})

# The profile a source with no policy sends (slice A's). A common desktop
# viewport, the whole page: Replicator refuses (``too_large``) rather than clips
# past 4096 x 32768 px.
DEFAULT_VIEWPORT = (DEFAULT_POLICY.viewport.width, DEFAULT_POLICY.viewport.height)
DEFAULT_FULL_PAGE = DEFAULT_POLICY.full_page

# A render is bounded by Replicator's 120 s fetch deadline and paced per host;
# a 5xx on the navigation is retried with no fact. An hour is many retries.
DEFAULT_REAP_HORIZON = timedelta(hours=1)

STATE_REQUESTED = "requested"
STATE_STORED = "stored"
STATE_FAILED = "failed"
STATE_ABANDONED = "abandoned"

# The reaper's local reason, persist's and replication's token for the same thing.
REASON_NO_FACT = "no_fact_before_horizon"

MAX_CAPTURE_REISSUES = 2
"""Re-issues of one silent capture: ``1 + MAX_CAPTURE_REISSUES`` commands, each
given the full horizon, before the reaper leaves it ``abandoned``."""


class CaptureDisabled(RuntimeError):
    """``ARCHIVER_CAPTURE_ENABLED`` is off: nothing may be enqueued."""


class CaptureAlreadyOpen(RuntimeError):
    """The source's latest command is still ``requested``."""


class CapturePolicyInvalid(ValueError):
    """The source's stored policy no longer validates: fix it before capturing."""


class ReapResult(NamedTuple):
    """One reaper pass: commands abandoned, and how many of those were re-issued."""

    abandoned: int
    reissued: int


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
    source = await _lock_source(session, info_source_id)
    if source is None:
        raise LookupError(f"no InfoSource {info_source_id}")
    try:
        policy = effective_policy(source.capture_policy)
    except ValidationError as e:
        raise CapturePolicyInvalid(f"InfoSource {info_source_id}'s capture policy: {e}") from e
    latest = await latest_capture(session, info_source_id)
    if latest is not None and latest.state == STATE_REQUESTED:
        raise CaptureAlreadyOpen(f"capture {latest.command_id} is still open")
    return _issue(
        session,
        source,
        viewport=policy.viewport_emit(),
        full_page=policy.full_page,
        wait=policy.wait_emit(),
        requested_by=requested_by,
    )


async def set_capture_policy(
    session: AsyncSession, info_source_id: ULID, policy: CapturePolicy | None
) -> InfoSource:
    """Store ``policy`` on the source, every default filled; ``None`` clears it. Caller commits.

    Raises :class:`LookupError` for an unknown source. Writes no command: a
    policy takes effect at the next click or revision.
    """
    source = await session.get(InfoSource, info_source_id)
    if source is None:
        raise LookupError(f"no InfoSource {info_source_id}")
    source.capture_policy = None if policy is None else policy.model_dump(mode="json")
    logger.info(
        "Capture policy set" if policy is not None else "Capture policy cleared",
        extra={
            "info_source_id": str(info_source_id),
            "on_revision": policy.on_revision if policy is not None else None,
        },
    )
    return source


async def capture_for_revision(
    session: AsyncSession,
    revision: SourceRevision,
    *,
    environ: Mapping[str, str] = os.environ,
) -> CaptureCommand | None:
    """Capture a new revision's source if its policy opts in (D3). Caller commits.

    ``None``, writing nothing, when the switch is off, the source has no policy
    or does not opt in, its stored policy no longer validates (logged: the
    revision must still land), or a command is already open. Called by
    ``record_revision`` for a genuinely new revision only, never a redelivery.
    """
    if not capture_enabled(environ):
        return None
    source = await session.get(InfoSource, revision.info_source_id)
    if source is None or source.capture_policy is None:
        return None
    policy = _policy_or_none(source)
    if policy is None or not policy.on_revision:
        return None
    await _lock_source(session, source.info_source_id)
    latest = await latest_capture(session, source.info_source_id)
    if latest is not None and latest.state == STATE_REQUESTED:
        logger.info(
            "New revision while a capture is open; not issuing another",
            extra={
                "info_source_id": str(source.info_source_id),
                "source_revision_id": str(revision.source_revision_id),
                "open_command_id": latest.command_id,
            },
        )
        return None
    return _issue(
        session,
        source,
        viewport=policy.viewport_emit(),
        full_page=policy.full_page,
        wait=policy.wait_emit(),
        requested_by=None,
        source_revision_id=revision.source_revision_id,
    )


def _policy_or_none(source: InfoSource) -> CapturePolicy | None:
    """The stored policy, or ``None`` (logged) when it no longer validates."""
    try:
        return effective_policy(source.capture_policy)
    except ValidationError as e:
        logger.warning(
            "Stored capture policy no longer validates; no revision capture",
            extra={"info_source_id": str(source.info_source_id), "error": str(e)},
        )
        return None


async def _lock_source(session: AsyncSession, info_source_id: ULID) -> InfoSource | None:
    """The source, row-locked, so two issuers cannot both pass the one-open check.

    ``FOR NO KEY UPDATE`` (``key_share=True``), not ``FOR UPDATE``: it still
    conflicts with itself, but not with the ``FOR KEY SHARE`` a revision insert's
    foreign key takes. ``record_revision`` inserts first and locks second, so
    ``FOR UPDATE`` could deadlock two writers for one source.
    """
    return (
        await session.execute(
            select(InfoSource)
            .where(InfoSource.info_source_id == info_source_id)
            .with_for_update(key_share=True)
        )
    ).scalar_one_or_none()


def _issue(
    session: AsyncSession,
    source: InfoSource,
    *,
    viewport: CaptureViewportEmit,
    full_page: bool,
    wait: Any,
    requested_by: ULID | None,
    source_revision_id: ULID | None = None,
    reissue_of: str | None = None,
    attempt: int = 1,
) -> CaptureCommand:
    """Add the command row and its outbox row; the row records what the wire carries."""
    now = datetime.now(UTC)
    command_id = str(ULID())
    emit = ContentCaptureCommandEmit(
        occurred_at=now,
        command_id=command_id,
        url=source.url,
        info_source_id=str(source.info_source_id),
        viewport=viewport,
        full_page=full_page,
        wait=wait,
    )
    payload = emit.model_dump(mode="json")
    command = CaptureCommand(
        command_id=command_id,
        info_source_id=source.info_source_id,
        url=source.url,
        viewport_width=emit.viewport.width,
        viewport_height=emit.viewport.height,
        full_page=emit.full_page,
        wait=payload["wait"],
        requested_by=requested_by,
        source_revision_id=source_revision_id,
        reissue_of=reissue_of,
        attempt=attempt,
        issued_at=now,
        state=STATE_REQUESTED,
    )
    session.add(command)
    session.add(ChangesOutboxRow(topic=CAPTURE_TOPIC, payload=payload))
    logger.info(
        "Capture requested",
        extra={
            "command_id": command_id,
            "info_source_id": str(source.info_source_id),
            "source_revision_id": str(source_revision_id) if source_revision_id else None,
            "reissue_of": reissue_of,
            "attempt": attempt,
        },
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
    # Keep it (C3): same transaction, so "stored" and "persist requested" land
    # together. A redelivered success returned above, so it issues nothing.
    await issue_capture_persist(session, command)
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
    session: AsyncSession,
    *,
    horizon: timedelta = DEFAULT_REAP_HORIZON,
    environ: Mapping[str, str] = os.environ,
) -> ReapResult:
    """Abandon commands open past ``horizon``, re-issuing each within the cap.

    The abandon and its re-issue share the caller's transaction. Does not commit.
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
    reissued = 0
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
                "attempt": command.attempt,
            },
        )
        await session.flush()
        if await _reissue(session, command, environ) is not None:
            reissued += 1
    await session.flush()
    return ReapResult(abandoned=len(stale), reissued=reissued)


async def _reissue(
    session: AsyncSession, command: CaptureCommand, environ: Mapping[str, str]
) -> CaptureCommand | None:
    """Re-send exactly what ``command`` sent, under a fresh id; ``None`` if not owed one."""
    if not capture_enabled(environ):
        return None
    if command.attempt > MAX_CAPTURE_REISSUES:
        logger.info(
            "Capture re-issue cap reached; leaving it abandoned",
            extra={"command_id": command.command_id, "attempt": command.attempt},
        )
        return None
    source = await _lock_source(session, command.info_source_id)
    if source is None:
        return None
    latest = await latest_capture(session, command.info_source_id)
    if latest is None or latest.command_id != command.command_id:
        return None
    return _issue(
        session,
        source,
        viewport=CaptureViewportEmit(width=command.viewport_width, height=command.viewport_height),
        full_page=command.full_page,
        wait=command.wait,
        requested_by=command.requested_by,
        source_revision_id=command.source_revision_id,
        reissue_of=command.command_id,
        attempt=command.attempt + 1,
    )


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
