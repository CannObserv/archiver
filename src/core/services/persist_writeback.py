"""Close a persist command from ``content.artifacts`` (archiver#276, cannobserv#493).

``replication_writeback``'s job for ``content.persist``, with two differences that
come from content addressing:

**The outcome belongs to the digest, not the command.** Neither fact carries a
``source_revision_id`` or ``info_source_id``: the permanent object is shared by
every revision whose raw bytes hash to it. The command row is how a fact is
recognised as ours; the digest is what a success is *about*. So a success stamps
``persisted_at`` on every revision whose ``blob_fingerprint`` matches, whichever
revision occasioned the command.

**``persisted_at`` is a minimum.** ``occurred_at`` is the fact's publish time, an
upper bound on the write. A redelivery that finds the object present re-emits
with a fresh stamp, and a later command for the same bytes gets a later one. The
earliest fact for the digest is the best-known time, so every success lowers
``persisted_at`` or leaves it alone, in whatever order facts arrive. The command's
own state keeps ``last_fact_at`` ordering for failures, the guard replication
uses; a success closes it ``persisted`` whatever order it arrives in.

``reason`` is opaque, as in replication. Of the two fixed tokens, ``blob_expired``
is terminal *for Archiver* too: recovering means fetching again, and only Watcher
fetches (#142). A later observation of the same content re-arms the persist.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import func, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.logging import get_logger
from src.core.models import PersistCommand, SourceRevision
from src.core.services.replication_writeback import UnknownCommandError

logger = get_logger(__name__)

STATE_REQUESTED = "requested"
STATE_PERSISTED = "persisted"
STATE_FAILED = "failed"
STATE_ABANDONED = "abandoned"

# Local: the success named a digest other than the one the command sent. The
# success Emit validates its digest, so this is a producer bug. Stamping the
# command's digest would point later publications at an object that may not
# exist, so the command closes failed and no revision is stamped.
REASON_DIGEST_MISMATCH = "digest_mismatch"


async def apply_persisted(
    session: AsyncSession,
    *,
    command_id: str,
    content_fingerprint: str,
    size_bytes: int,
    occurred_at: datetime,
) -> PersistCommand:
    """Record ``blob_persisted``: close the command, stamp the digest's revisions.

    Idempotent and order-independent: the revision stamp is a ``LEAST``, and the
    command's fields are assignments of the same values. Does not commit.

    Raises:
        UnknownCommandError: the registry never issued this command.
    """
    command = await _load(session, command_id)

    if content_fingerprint != command.content_fingerprint:
        logger.error(
            "Persist success names a different digest than its command; stamping nothing",
            extra={
                "command_id": command_id,
                "sent_fingerprint": command.content_fingerprint,
                "fact_fingerprint": content_fingerprint,
            },
        )
        if command.state != STATE_PERSISTED:
            _close(command, STATE_FAILED, occurred_at)
            command.reason = REASON_DIGEST_MISMATCH
            command.detail = f"fact named {content_fingerprint!r}"
        return command

    # Every success is evidence about the digest, even one that is stale for the
    # command's own ordering: it only ever lowers the minimum.
    await session.execute(
        update(SourceRevision)
        .where(SourceRevision.blob_fingerprint == content_fingerprint)
        .values(
            persisted_at=func.least(
                func.coalesce(SourceRevision.persisted_at, occurred_at), occurred_at
            )
        )
        .execution_options(synchronize_session="fetch")
    )

    # A success wins whatever its arrival order: the object exists once any fact
    # says so, and a failure stamped later cannot unmake it. The mirror of
    # apply_persist_failed ignoring failures after a success.
    command.size_bytes = size_bytes
    command.reason = None
    command.detail = None
    _close(command, STATE_PERSISTED, occurred_at)

    logger.info(
        "Blob persisted",
        extra={
            "command_id": command_id,
            "content_fingerprint": content_fingerprint,
            "source_revision_id": str(command.source_revision_id),
            "size_bytes": size_bytes,
            "occurred_at": occurred_at.isoformat(),
        },
    )
    return command


async def apply_persist_failed(
    session: AsyncSession,
    *,
    command_id: str,
    reason: str,
    terminal: bool,
    detail: str | None,
    occurred_at: datetime,
) -> PersistCommand:
    """Record ``persist_failed``; close the command only when ``terminal``.

    A failure never touches ``persisted_at``, and never overrides a success
    already recorded: the object exists either way. Does not commit.

    Raises:
        UnknownCommandError: the registry never issued this command.
    """
    command = await _load(session, command_id)
    if command.state == STATE_PERSISTED:
        logger.warning(
            "Ignoring a failure fact for an already-persisted command",
            extra={"command_id": command_id, "reason": reason, "terminal": terminal},
        )
        return command
    if _is_stale(command, occurred_at):
        logger.info(
            "Ignoring a persist fact older than one already applied",
            extra={
                "command_id": command_id,
                "occurred_at": occurred_at.isoformat(),
                "last_fact_at": command.last_fact_at.isoformat(),
            },
        )
        return command

    command.reason = reason
    command.detail = detail
    command.terminal = terminal
    command.last_fact_at = occurred_at
    if terminal:
        _close(command, STATE_FAILED, occurred_at)

    logger.log(
        logging.WARNING if terminal else logging.INFO,
        "Persist failed" if terminal else "Persist attempt failed; still retrying",
        extra={
            "command_id": command_id,
            "content_fingerprint": command.content_fingerprint,
            "reason": reason,
            "terminal": terminal,
            "occurred_at": occurred_at.isoformat(),
        },
    )
    return command


async def _load(session: AsyncSession, command_id: str) -> PersistCommand:
    command = await session.get(PersistCommand, command_id)
    if command is None:
        raise UnknownCommandError(command_id)
    return command


def _is_stale(command: PersistCommand, occurred_at: datetime) -> bool:
    """Older than the newest fact already applied. Equal is the same emission."""
    return command.last_fact_at is not None and occurred_at < command.last_fact_at


def _close(command: PersistCommand, state: str, occurred_at: datetime) -> None:
    command.state = state
    command.terminal = True
    # A high-water mark: a late success must not wind it back, or an even older
    # failure redelivered afterwards would pass the staleness check.
    if command.last_fact_at is None or occurred_at > command.last_fact_at:
        command.last_fact_at = occurred_at
    if command.closed_at is None:
        command.closed_at = datetime.now(UTC)
