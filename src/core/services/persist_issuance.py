"""Issue ``content.persist`` for an observed revision (archiver#276, replicator#114).

A persist asks Replicator to copy a revision's raw bytes out of its seven-day
temp store into its permanent, content-addressed one. Once ``blob_persisted``
comes back (``persist_writeback``), replication publishes from the permanent
URI with no expiry, so a revision missed inside the temp window is no longer
lost for good. The normative obligations are Replicator's
``content-persist-issuer-contract.md`` (P1-P5).

**Off unless switched on.** ``ARCHIVER_PERSIST_ISSUANCE`` gates issuance and the
reaper's re-issue. The go-live order is broker, then Replicator's
``REPLICATOR_PERSIST_ENABLED``, then Archiver (broker#64): Replicator creates
``replicator.persist`` at ``$``, so a command sent before that group existed is
never delivered. A switch lets the code ship on its own schedule.

**When a command is issued** (decision 3):

- on a new revision (P1: issue on receipt, inside the temp window), and
- on a re-observation that refreshed the blob reference, while the revision is
  unpersisted and no command for its bytes is open. This is the retry path
  after any terminal ``persist_failed`` or a lost command. Every refusal token
  gets the same answer, so ``reason`` stays opaque (P3): ``blob_expired`` and
  ``source_corrupt`` need a fresh fetch, which only Watcher makes (#142) and
  which arrives as exactly such a re-observation; ``store_refused`` needs the
  operator, after which the next re-observation re-issues.

**One open command per digest.** The stored object belongs to the digest, and a
success stamps ``persisted_at`` on every revision carrying it, so a second open
command for identical bytes buys nothing.

**The pair is sent as recorded (P4).** ``blob_fingerprint`` and
``content_cache_uri`` come from the same observation (decision 2, enforced in
``source_revision._refresh_cache_reference``); the URI is never rebuilt.

**The reaper re-issues (P3).** A store 5xx is retried by Replicator with no fact
at all, so silence means "still trying" or "lost". Unlike ``replicate`` - whose
reaper only abandons, because a re-issue can write a second artefact into a
store nothing may delete from - a duplicate persist is a no-op success on a
content-addressed key, so re-issuing is safe. It is capped per digest.

Nothing here commits: rows are added to the caller's session, so "revision
recorded" and "persist requested" land in one transaction, through the outbox.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

from co_core.pure.adapters.bus.streams import CONTENT_PERSIST
from co_core.pure.models.changes import ContentPersistCommandEmit
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.core.logging import get_logger
from src.core.models import ChangesOutboxRow, PersistCommand, SourceRevision
from src.core.services.persist_writeback import STATE_ABANDONED, STATE_REQUESTED

logger = get_logger(__name__)

ISSUANCE_ENV = "ARCHIVER_PERSIST_ISSUANCE"
_TRUTHY = frozenset({"1", "true", "yes", "on"})

# Matches replication_issuance.DEFAULT_MEDIA_TYPE: Replicator stores the type as
# object metadata on the first write and cannot recover it from bytes.
DEFAULT_MEDIA_TYPE = "application/octet-stream"

# The reaper's local reason, replication's token for the same observation.
REASON_NO_FACT = "no_fact_before_horizon"

# How long a command may stay open before the reaper calls it silent. A persist
# is a single same-cloud copy, normally seconds; the margin covers Replicator
# retrying a store 5xx. Six hours leaves a temp blob (>= 7 days) many retries.
DEFAULT_REAP_HORIZON = timedelta(hours=6)

# Re-issues per digest after the original. Past it, the digest stays abandoned
# until a re-observation re-arms it: something is wrong that retrying on a
# timer will not fix, and the WARNING says so.
MAX_REISSUES = 3


def issuance_enabled(raw: str | None = None) -> bool:
    """Whether ``ARCHIVER_PERSIST_ISSUANCE`` switches issuance on.

    Read at call time rather than at import, so enabling it needs a restart of
    nothing but the variable's reader, and tests can set it per case.
    """
    value = os.environ.get(ISSUANCE_ENV) if raw is None else raw
    return (value or "").strip().lower() in _TRUTHY


def _eligible(revision: SourceRevision) -> bool:
    return (
        revision.blob_fingerprint is not None
        and bool(revision.content_cache_uri)
        and revision.persisted_at is None
    )


async def _open_command_for(session: AsyncSession, digest: str) -> bool:
    result = await session.execute(
        select(PersistCommand.command_id)
        .where(
            PersistCommand.content_fingerprint == digest,
            PersistCommand.state == STATE_REQUESTED,
            PersistCommand.closed_at.is_(None),
        )
        .limit(1)
    )
    return result.first() is not None


async def issue_persist(session: AsyncSession, revision: SourceRevision) -> PersistCommand | None:
    """Enqueue one persist for ``revision``'s bytes, or ``None`` when not warranted.

    ``None`` covers: switched off, no digest or no blob reference, already
    persisted, or a command for these bytes already open. Does not commit.
    """
    if not issuance_enabled() or not _eligible(revision):
        return None
    digest = revision.blob_fingerprint
    if await _open_command_for(session, digest):
        logger.debug(
            "A persist for these bytes is already open; not issuing another",
            extra={"source_revision_id": str(revision.source_revision_id), "digest": digest},
        )
        return None

    command_id = str(ULID())
    media_type = revision.source_media_type or DEFAULT_MEDIA_TYPE
    try:
        emit = ContentPersistCommandEmit(
            occurred_at=datetime.now(UTC),
            command_id=command_id,
            content_fingerprint=digest,
            blob_uri=revision.content_cache_uri,
            media_type=media_type,
        )
    except ValidationError as e:
        # The consumer validated the digest on ingest, so this is unreachable
        # today. Logged and skipped rather than raised: it runs inside the
        # content.revisions transaction, and a persist must not cost the revision.
        logger.error(
            "Revision does not produce a valid content.persist command; not issuing",
            extra={"source_revision_id": str(revision.source_revision_id), "error": str(e)},
        )
        return None

    command = PersistCommand(
        command_id=command_id,
        source_revision_id=revision.source_revision_id,
        content_fingerprint=digest,
        blob_uri=revision.content_cache_uri,
        media_type=media_type,
        state=STATE_REQUESTED,
    )
    session.add(command)
    session.add(ChangesOutboxRow(topic=CONTENT_PERSIST, payload=emit.model_dump(mode="json")))
    logger.info(
        "Persist requested",
        extra={
            "command_id": command_id,
            "source_revision_id": str(revision.source_revision_id),
            "digest": digest,
        },
    )
    return command


async def reap_open_persists(
    session: AsyncSession, *, horizon: timedelta = DEFAULT_REAP_HORIZON
) -> tuple[int, int]:
    """Abandon silent commands and re-issue for their bytes. Returns ``(abandoned, reissued)``.

    Re-issues once per **digest**, not per occasioning revision: decision 2 may
    have moved that revision to new bytes (which then got a command of their
    own), while other revisions still carry the abandoned digest. The re-issue
    comes from an eligible revision carrying it, the one with the latest
    horizon, so the freshest temp blob is read. Only while switched on, no other
    command for the digest is open, and the digest has been abandoned no more
    than ``MAX_REISSUES`` times. Does not commit.
    """
    cutoff = datetime.now(UTC) - horizon
    stale = list(
        (
            await session.execute(
                select(PersistCommand)
                .where(
                    PersistCommand.state == STATE_REQUESTED,
                    PersistCommand.closed_at.is_(None),
                    PersistCommand.issued_at <= cutoff,
                )
                .order_by(PersistCommand.issued_at)
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
            "Persist command produced no fact before the horizon; abandoning",
            extra={
                "command_id": command.command_id,
                "digest": command.content_fingerprint,
                "issued_at": command.issued_at.isoformat(),
                "horizon_hours": horizon.total_seconds() / 3600,
            },
        )
    await session.flush()

    reissued = 0
    if not issuance_enabled():
        return len(stale), reissued
    seen: set[str] = set()
    for command in stale:
        digest = command.content_fingerprint
        if digest in seen:
            continue
        seen.add(digest)
        abandoned = (
            await session.execute(
                select(func.count())
                .select_from(PersistCommand)
                .where(
                    PersistCommand.content_fingerprint == digest,
                    PersistCommand.state == STATE_ABANDONED,
                )
            )
        ).scalar_one()
        if abandoned > MAX_REISSUES:
            logger.warning(
                "Persist re-issue cap reached; leaving the digest to a re-observation",
                extra={"digest": digest, "abandoned": abandoned, "max_reissues": MAX_REISSUES},
            )
            continue
        revision = await _freshest_carrier(session, digest)
        if revision is not None and await issue_persist(session, revision) is not None:
            reissued += 1
    return len(stale), reissued


async def _freshest_carrier(session: AsyncSession, digest: str) -> SourceRevision | None:
    """An unpersisted revision still carrying ``digest``, latest horizon first.

    A NULL horizon (unknown) sorts last: a known live blob beats a guess.
    """
    result = await session.execute(
        select(SourceRevision)
        .where(
            SourceRevision.blob_fingerprint == digest,
            SourceRevision.persisted_at.is_(None),
            SourceRevision.content_cache_uri.is_not(None),
        )
        .order_by(
            SourceRevision.content_cache_expires_at.desc().nulls_last(),
            SourceRevision.source_revision_id.desc(),
        )
        .limit(1)
    )
    return result.scalar_one_or_none()
