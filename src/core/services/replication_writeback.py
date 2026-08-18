"""Close a replication command from ``content.artifacts`` (archiver#170).

The point of the whole exercise: ``info_item_rep_specs.public_url`` has been a
column with no automated writer since RepSpecs were built. A
``replication_complete`` fact is what fills it.

Three properties from the issuer contract shape the code, and none of them is
obvious from the happy path:

**A repeat is expected traffic** (MUST-4). T4's no-op row has Replicator re-emit
the *same* ``public_url`` when a redelivery finds matching bytes already at the
destination, so "this command is already complete" is a normal arrival, not an
anomaly to log loudly.

**``terminal`` decides whether the command closes** (MUST-6). Every *documented*
refusal is terminal, but a provider 5xx is not: it leaves the command open,
retries unbounded, and publishes no fact at all while it does. Treating any
failure as final would close a command Replicator is still working on.

**``public_url`` is not stable across occasions** (R3). Each occasion writes its
own artifact at its own path, so the assignment row holds the *newest* occasion's
URL and an older occasion's late-arriving fact records itself without clobbering
it. The command row keeps the history either way.

``reason`` is stored as an opaque string. The vocabulary is producer-owned —
Replicator's contract lists six tokens where co-core's docstring registers five
(cannobserv#330) — so branching on it here would make every new token a code
change on this side.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.logging import get_logger
from src.core.models import InfoItemRepSpec, ReplicationCommand
from src.core.services.replication_issuance import STATE_REQUESTED

logger = get_logger(__name__)

STATE_COMPLETE = "complete"
STATE_FAILED = "failed"
STATE_ABANDONED = "abandoned"

# The reaper's local reason — Archiver's own observation that nothing ever came
# back, not a token Replicator emitted. Kept distinct from the failure vocabulary
# for the same reason the issuance skips are.
REASON_NO_FACT = "no_fact_before_horizon"

# How long a command may stay open before the reaper calls it. Generous on
# purpose: Replicator's retry for a transient provider failure is *unbounded* and
# silent, so a horizon sized against a delivery ceiling would abandon commands
# that are still being worked. Abandoned means "nothing came back in time", never
# "this definitely failed".
DEFAULT_REAP_HORIZON = timedelta(hours=6)


class UnknownCommandError(Exception):
    """The fact names a ``command_id`` the registry does not hold.

    Not poison and not retryable: the registry is the authority on what it
    issued, so a fact about something else is ack-and-drop — the same posture
    ``content.revisions`` takes for an unknown ``info_source_id``. Raised rather
    than swallowed so the consumer decides the disposition and logs it once.
    """

    def __init__(self, command_id: str) -> None:
        self.command_id = command_id
        super().__init__(f"no replication command with id {command_id!r}")


async def apply_success(
    session: AsyncSession,
    *,
    command_id: str,
    public_url: str,
    occurred_at: datetime,
) -> ReplicationCommand:
    """Record ``replication_complete`` and write ``public_url`` back.

    Idempotent by construction: every write is an assignment of the same values,
    so a redelivery — or T4's deliberate re-emission — lands on the same state.
    ``closed_at`` is stamped once and kept, so a repeat does not move the clock.

    Does not commit; the caller owns the transaction (ack-after-commit).

    Raises:
        UnknownCommandError: the registry never issued this command.
    """
    command = await _load(session, command_id)

    command.public_url = public_url
    command.state = STATE_COMPLETE
    command.terminal = True
    if command.closed_at is None:
        command.closed_at = datetime.now(UTC)

    if await _is_newest_occasion(session, command):
        assignment = await session.get(InfoItemRepSpec, command.info_item_rep_spec_id)
        if assignment is not None:
            # Written even when the assignment has since been deactivated: the
            # bytes are at that URL either way, and the row is the historical
            # record of what this spec produced.
            assignment.public_url = public_url
    else:
        logger.info(
            "Replication completed for a superseded occasion; assignment keeps the newer URL",
            extra={
                "command_id": command_id,
                "info_item_rep_spec_id": str(command.info_item_rep_spec_id),
                "public_url": public_url,
            },
        )

    logger.info(
        "Replication complete",
        extra={
            "command_id": command_id,
            "info_item_rep_spec_id": str(command.info_item_rep_spec_id),
            "source_revision_id": str(command.source_revision_id),
            "public_url": public_url,
            "occurred_at": occurred_at.isoformat(),
        },
    )
    return command


async def apply_failure(
    session: AsyncSession,
    *,
    command_id: str,
    reason: str,
    terminal: bool,
    attempts: int | None,
    detail: str | None,
    occurred_at: datetime,
) -> ReplicationCommand:
    """Record ``replication_failed``; close the command only when ``terminal``.

    A non-terminal failure updates the diagnostics and leaves ``state`` at
    ``requested`` — Replicator is still retrying, and the reaper's horizon is
    what eventually decides that the silence has gone on too long.

    ``public_url`` is untouched: a failed occasion says nothing about the
    artifact an earlier occasion wrote.

    Does not commit; the caller owns the transaction.

    Raises:
        UnknownCommandError: the registry never issued this command.
    """
    command = await _load(session, command_id)

    command.reason = reason
    command.terminal = terminal
    command.attempts = attempts
    command.detail = detail
    if terminal:
        command.state = STATE_FAILED
        if command.closed_at is None:
            command.closed_at = datetime.now(UTC)

    logger.log(
        30 if terminal else 20,  # WARNING when closed, INFO while retrying
        "Replication failed" if terminal else "Replication attempt failed; still retrying",
        extra={
            "command_id": command_id,
            "info_item_rep_spec_id": str(command.info_item_rep_spec_id),
            "reason": reason,
            "terminal": terminal,
            "attempts": attempts,
            "occurred_at": occurred_at.isoformat(),
        },
    )
    return command


async def reap_open_commands(
    session: AsyncSession, *, horizon: timedelta = DEFAULT_REAP_HORIZON
) -> int:
    """Close commands that produced no fact at all. Returns how many.

    MUST-6 exists because Replicator does not guarantee that every command either
    succeeds or is closed — a provider 5xx retries unbounded and publishes
    nothing while it does, and a frame can be lost outright. Without this, such a
    command stays ``requested`` forever and the dashboard reports a replication
    in flight that nobody is working on.

    **It does not re-issue.** This capability writes into permanent stores, one of
    which (archive.org) cannot be deleted at all, so an automatic retry could
    publish a second artifact for the same occasion with no way back. Re-issue
    stays an operator act.

    Does not commit; the caller owns the transaction.
    """
    cutoff = datetime.now(UTC) - horizon
    result = await session.execute(
        select(ReplicationCommand).where(
            ReplicationCommand.state == STATE_REQUESTED,
            ReplicationCommand.closed_at.is_(None),
            ReplicationCommand.issued_at <= cutoff,
        )
    )
    stale = list(result.scalars().all())
    now = datetime.now(UTC)
    for command in stale:
        command.state = STATE_ABANDONED
        command.reason = REASON_NO_FACT
        command.closed_at = now
        logger.warning(
            "Replication command produced no fact before the horizon; abandoning",
            extra={
                "command_id": command.command_id,
                "info_item_rep_spec_id": str(command.info_item_rep_spec_id),
                "issued_at": command.issued_at.isoformat(),
                "horizon_hours": horizon.total_seconds() / 3600,
            },
        )
    return len(stale)


async def _load(session: AsyncSession, command_id: str) -> ReplicationCommand:
    command = await session.get(ReplicationCommand, command_id)
    if command is None:
        raise UnknownCommandError(command_id)
    return command


async def _is_newest_occasion(session: AsyncSession, command: ReplicationCommand) -> bool:
    """Whether this command is the latest issuance for its assignment.

    The guard behind R3. Occasions are ordered by ``issued_at`` (the index
    ``ix_replication_commands_target`` covers exactly this lookup); ties fall back
    to ``command_id``, which is ULID-shaped and therefore monotonic within a
    millisecond — so two occasions minted in the same instant still order
    deterministically rather than by whichever fact arrived first.
    """
    result = await session.execute(
        select(ReplicationCommand.command_id)
        .where(ReplicationCommand.info_item_rep_spec_id == command.info_item_rep_spec_id)
        .order_by(ReplicationCommand.issued_at.desc(), ReplicationCommand.command_id.desc())
        .limit(1)
    )
    newest_id = result.scalar_one_or_none()
    return newest_id is None or newest_id == command.command_id
