"""Issue ``content.replicate`` for a newly-recorded revision (archiver#169).

Step 5 of the decoupling epic (#137): Archiver becomes the replication issuer.
On a genuinely new SourceRevision, every *active* ``info_item_rep_specs``
assignment reachable from that revision gets one command — never one command
carrying a list, because a ``command_id`` identifies an occasion and N provider
writes fail, retry and complete independently (MUST-1).

**Transactional, through the existing outbox.** The command row and the outbox
row are added to the caller's session alongside the revision insert, so
"revision recorded" and "replication requested" cannot diverge. Archiver already
owns the producer-side guarantee the issuer contract asks for; publishing from
the consumer's hot path would throw it away.

**Nothing here fetches, extracts, or opens a blob.** ``blob_uri`` is passed
through; Replicator reads the bytes. The registry stays the registry.

**Every refusal is recorded.** A skipped assignment writes a row with
``state="skipped"`` and a local reason, because the alternative — a log line —
renders in the dashboard as "not replicated yet" forever (archiver#171). The
skip vocabulary is *local* and deliberately distinct from Replicator's failure
tokens: these are conditions Archiver decided about before publishing, and
naming them ``blob_expired`` would blur who observed what.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from co_core.pure.adapters.bus.streams import CONTENT_REPLICATE
from co_core.pure.models.changes import ContentReplicateCommandEmit
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.core.logging import get_logger
from src.core.models import (
    ChangesOutboxRow,
    InfoItem,
    InfoItemRepSpec,
    InfoItemSource,
    ReplicationCommand,
    RepSpec,
    SourceRevision,
)
from src.core.replication.destination import (
    DestinationCollisionError,
    RenderOccasion,
    assert_distinct_destinations,
    render_destination,
)
from src.core.replication.errors import ReplicationRenderError

logger = get_logger(__name__)

CONTENT_REPLICATE_TOPIC = CONTENT_REPLICATE

STATE_REQUESTED = "requested"
STATE_SKIPPED = "skipped"

# Local skip reasons — what Archiver decided *before* publishing. Distinct from
# ``ReplicationFailedEvent.reason``, which is Replicator's vocabulary for what it
# observed after receiving a command.
SKIP_BLOB_ABSENT = "blob_absent"
SKIP_BLOB_EXPIRED = "blob_expired_locally"
SKIP_UNRENDERABLE = "unrenderable"
SKIP_DESTINATION_COLLISION = "destination_collision"
SKIP_UNSUPPORTED_COMMAND = "unsupported_command"

# The consumer holds bytes and nothing else — its blob store discards the media
# type it was handed — so an omitted value writes application/octet-stream into a
# permanent store. Where the registry has no stored value, saying so explicitly
# is the honest substitution; the fetch side already makes it for an origin that
# sent no header.
DEFAULT_MEDIA_TYPE = "application/octet-stream"


@dataclass(frozen=True, slots=True)
class _Target:
    """One active assignment, with everything a command needs."""

    assignment: InfoItemRepSpec
    document: dict
    rep_fields: dict


async def issue_for_revision(
    session: AsyncSession, revision: SourceRevision
) -> list[ReplicationCommand]:
    """Mint and enqueue one command per active assignment. Returns the published ones.

    Skipped assignments are persisted too (``state="skipped"``) but are not in
    the return value — the caller's interest is what went on the wire.

    Does not commit: rows are added to ``session`` so they land in the caller's
    transaction alongside the revision.
    """
    targets = await _active_targets(session, revision)
    if not targets:
        logger.debug(
            "Revision has no active RepSpec assignments; nothing to replicate",
            extra={"source_revision_id": str(revision.source_revision_id)},
        )
        return []

    blob_skip = _blob_skip_reason(revision)
    if blob_skip is not None:
        _record_skips(session, revision, targets, blob_skip)
        logger.warning(
            "Revision cannot be replicated: %s",
            blob_skip,
            extra={
                "source_revision_id": str(revision.source_revision_id),
                "assignments": len(targets),
            },
        )
        return []

    occasion = RenderOccasion(
        source_revision_id=str(revision.source_revision_id),
        content_fingerprint=revision.content_fingerprint,
        captured_at=revision.captured_at,
    )

    rendered: dict[str, str] = {}
    renderable: list[_Target] = []
    for target in targets:
        try:
            rendered[str(target.assignment.id)] = render_destination(
                target.document.get("path_template", ""),
                rep_fields=target.rep_fields,
                occasion=occasion,
            )
        except ReplicationRenderError as e:
            _record_skips(session, revision, [target], SKIP_UNRENDERABLE, detail=str(e))
            logger.warning(
                "Assignment cannot render a destination; skipping replication",
                extra={
                    "info_item_rep_spec_id": str(target.assignment.id),
                    "source_revision_id": str(revision.source_revision_id),
                    "error": str(e),
                },
            )
            continue
        renderable.append(target)

    try:
        assert_distinct_destinations(rendered)
    except DestinationCollisionError as e:
        # Publishing both would return as destination_conflict, which reports a
        # conflict rather than the path-design error it is. Refuse the whole
        # set: which of two identical destinations is "the right one" is not a
        # question this service can answer.
        _record_skips(session, revision, renderable, SKIP_DESTINATION_COLLISION, detail=str(e))
        logger.error(
            "Assignments render the same destination; skipping replication",
            extra={
                "source_revision_id": str(revision.source_revision_id),
                "error": str(e),
            },
        )
        return []

    issued: list[ReplicationCommand] = []
    for target in renderable:
        command = _issue_one(session, revision, target, rendered[str(target.assignment.id)])
        if command is not None:
            issued.append(command)
    return issued


def _issue_one(
    session: AsyncSession,
    revision: SourceRevision,
    target: _Target,
    destination: str,
) -> ReplicationCommand | None:
    """Persist the mapping, then enqueue the emit. Returns None on a skip."""
    command_id = str(ULID())
    media_type = revision.source_media_type or DEFAULT_MEDIA_TYPE
    object_options = target.document.get("object_options") or None

    try:
        emit = ContentReplicateCommandEmit(
            occurred_at=datetime.now(UTC),
            command_id=command_id,
            blob_uri=revision.content_cache_uri or "",
            media_type=media_type,
            provider=target.document.get("provider", ""),
            credentials_alias=target.document.get("credentials_alias", ""),
            destination=destination,
            object_options=object_options,
            info_item_rep_spec_id=str(target.assignment.id),
            source_revision_id=str(revision.source_revision_id),
            info_source_id=str(revision.info_source_id),
        )
    except ValidationError as e:
        # The Emit variant pins ``provider`` to a Literal, so an unsupported one
        # fails here rather than dead-lettering in the drain loop. Recorded as a
        # skip: this runs inside the content.revisions consumer's transaction,
        # and one unsupported RepSpec must not cost the revision.
        _record_skips(
            session,
            revision,
            [target],
            SKIP_UNSUPPORTED_COMMAND,
            detail=str(e),
            destination=destination,
        )
        logger.error(
            "RepSpec does not produce a valid content.replicate command; skipping",
            extra={
                "info_item_rep_spec_id": str(target.assignment.id),
                "provider": target.document.get("provider"),
                "error": str(e),
            },
        )
        return None

    command = ReplicationCommand(
        command_id=command_id,
        info_item_rep_spec_id=target.assignment.id,
        source_revision_id=revision.source_revision_id,
        info_source_id=revision.info_source_id,
        provider=emit.provider,
        credentials_alias=emit.credentials_alias,
        destination=destination,
        media_type=media_type,
        blob_uri=revision.content_cache_uri,
        object_options=object_options,
        state=STATE_REQUESTED,
    )
    session.add(command)
    session.add(
        ChangesOutboxRow(topic=CONTENT_REPLICATE_TOPIC, payload=emit.model_dump(mode="json"))
    )
    return command


def _blob_skip_reason(revision: SourceRevision) -> str | None:
    """Whether the bytes this command would copy are still there to copy.

    MUST-7 inverts for replication: the *issuer* schedules against the horizon,
    because the blob's TTL clock runs from last fetch reference rather than last
    read. Archiver cannot repair an expired blob — Watcher issues
    ``content.fetch`` and archiver#142 leaves no call to make — so an expired
    horizon is surfaced, not retried. A NULL horizon records that the expiry is
    unknown, which is not the same as knowing it has passed.
    """
    if not revision.content_cache_uri:
        return SKIP_BLOB_ABSENT
    expires_at = revision.content_cache_expires_at
    if expires_at is not None and expires_at <= datetime.now(UTC):
        return SKIP_BLOB_EXPIRED
    return None


def _record_skips(
    session: AsyncSession,
    revision: SourceRevision,
    targets: Sequence[_Target],
    reason: str,
    *,
    detail: str | None = None,
    destination: str | None = None,
) -> None:
    """Write one terminal row per assignment that will not be published.

    A ``command_id`` is minted even though nothing goes on the wire: the id names
    the *occasion* the registry considered, which is what the dashboard renders
    and what a later manual re-issue is distinct from.
    """
    now = datetime.now(UTC)
    for target in targets:
        session.add(
            ReplicationCommand(
                command_id=str(ULID()),
                info_item_rep_spec_id=target.assignment.id,
                source_revision_id=revision.source_revision_id,
                info_source_id=revision.info_source_id,
                provider=target.document.get("provider", ""),
                credentials_alias=target.document.get("credentials_alias", ""),
                destination=destination,
                media_type=revision.source_media_type or DEFAULT_MEDIA_TYPE,
                blob_uri=revision.content_cache_uri,
                object_options=target.document.get("object_options") or None,
                state=STATE_SKIPPED,
                reason=reason,
                detail=detail,
                closed_at=now,
            )
        )


async def _active_targets(session: AsyncSession, revision: SourceRevision) -> list[_Target]:
    """Every active assignment reachable from this revision's InfoSource.

    Reachability is *active bindings only*: a previous primary is kept as
    succession history, and replicating through it would attribute new content
    to an item that no longer draws from this source.
    """
    result = await session.execute(
        select(InfoItemRepSpec, RepSpec, InfoItem)
        .join(InfoItem, InfoItem.info_item_id == InfoItemRepSpec.info_item_id)
        .join(RepSpec, RepSpec.rep_spec_id == InfoItemRepSpec.rep_spec_id)
        .join(InfoItemSource, InfoItemSource.info_item_id == InfoItemRepSpec.info_item_id)
        .where(
            InfoItemSource.info_source_id == revision.info_source_id,
            InfoItemSource.deactivated_at.is_(None),
            InfoItemRepSpec.deactivated_at.is_(None),
        )
        .order_by(InfoItemRepSpec.id)
    )
    return [
        _Target(
            assignment=assignment, document=spec.document or {}, rep_fields=item.rep_fields or {}
        )
        for assignment, spec, item in result.all()
    ]
