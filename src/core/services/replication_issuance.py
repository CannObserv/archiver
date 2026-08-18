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

import logging
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
    RenderOccasion,
    find_collisions,
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


class ManualIssuanceError(Exception):
    """A manual re-issue could not even be *attempted* (archiver#171).

    Distinct from a skip on purpose. A skip is an occasion the registry
    considered and declined, and it leaves a row; these are conditions under
    which there is no occasion to consider — no live assignment, no bound source,
    no content. Writing a skip row for them would invent an occasion that never
    existed.
    """

    def __init__(self, assignment_id, message: str) -> None:
        self.assignment_id = assignment_id
        super().__init__(message)


class AssignmentNotActiveError(ManualIssuanceError):
    """The assignment has been deactivated."""

    def __init__(self, assignment_id) -> None:
        super().__init__(assignment_id, f"assignment {assignment_id} is not active")


class NoActiveSourceError(ManualIssuanceError):
    """The InfoItem has no active InfoSource binding to replicate from."""

    def __init__(self, assignment_id) -> None:
        super().__init__(assignment_id, f"assignment {assignment_id} has no active source binding")


class NoRevisionError(ManualIssuanceError):
    """The bound source has never been captured, so there are no bytes to copy."""

    def __init__(self, assignment_id) -> None:
        super().__init__(assignment_id, f"assignment {assignment_id} has no revision to replicate")


class AssignmentUnreachableError(ManualIssuanceError):
    """The assignment is not in the collision domain its own revision produced.

    Defensive: every join in ``_active_targets`` is guaranteed by the lookups
    ``issue_for_assignment`` already made, so there is no path here today. It is
    raised rather than returning ``None`` because ``None`` is what a *recorded
    skip* returns, and the two mean opposite things — a skip is an occasion the
    registry considered and declined, this is nothing happening and nothing being
    written. Collapsing them lets the dashboard re-render an older ``complete``
    occasion and read as success (archiver#171 CR #31).
    """

    def __init__(self, assignment_id) -> None:
        super().__init__(
            assignment_id,
            f"assignment {assignment_id} is absent from its own revision's active targets",
        )


# The refusal vocabulary, beside the exceptions it keys on. It lived in the
# dashboard route until archiver#171 CR #34: a service owns its vocabulary end to
# end — the skip reasons above are constants here, not strings at the call site —
# and splitting it across two modules is what let a subclass be added without a
# matching entry (CR #28). ``manual_issuance_refusal`` falls back rather than
# raising KeyError, so an unregistered subclass still surfaces as the 422 it is.
MANUAL_ISSUANCE_REFUSALS: dict[type[ManualIssuanceError], tuple[str, str]] = {
    AssignmentNotActiveError: ("not_active", "This assignment is not active"),
    NoActiveSourceError: (
        "no_active_source",
        "This Information Item has no active source binding to replicate from",
    ),
    NoRevisionError: (
        "no_revision",
        "The bound source has not been captured yet; there is nothing to replicate",
    ),
    AssignmentUnreachableError: (
        "assignment_unreachable",
        "This assignment could not be resolved against its own source; nothing was issued",
    ),
}

_GENERIC_REFUSAL = ("issuance_refused", "This replication could not be issued")


def manual_issuance_refusal(error: ManualIssuanceError) -> tuple[str, str]:
    """``(code, message)`` for a refusal. Never raises on an unregistered subclass."""
    return MANUAL_ISSUANCE_REFUSALS.get(type(error), _GENERIC_REFUSAL)


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
    return _issue_targets(session, revision, targets, requested={t.assignment.id for t in targets})


async def issue_for_assignment(
    session: AsyncSession, assignment: InfoItemRepSpec
) -> ReplicationCommand | None:
    """Issue one occasion for *assignment* against its item's latest revision.

    The operator's way out of a real gap (archiver#171): a new assignment on
    *stable* content never replicates, because nothing issues until the next
    revision arrives and for a stable InfoItem that may be never.

    Deliberately the **same pipeline** as the automatic path rather than a second
    one — blob guard, render, and the full collision domain. Narrowing the
    collision domain to the single requested assignment would let the manual
    button publish exactly what the automatic path refuses.

    Returns ``None`` when the occasion was refused; the skip row is persisted, so
    the refusal is something the dashboard can render rather than a log line.
    Does not commit.

    Raises:
        AssignmentNotActiveError: the assignment has been deactivated.
        NoActiveSourceError: the InfoItem has no active InfoSource binding.
        NoRevisionError: the bound source has never been captured.
    """
    if assignment.deactivated_at is not None:
        raise AssignmentNotActiveError(assignment.id)

    binding = (
        await session.execute(
            select(InfoItemSource).where(
                InfoItemSource.info_item_id == assignment.info_item_id,
                InfoItemSource.deactivated_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if binding is None:
        raise NoActiveSourceError(assignment.id)

    revision = (
        await session.execute(
            select(SourceRevision)
            .where(SourceRevision.info_source_id == binding.info_source_id)
            .order_by(SourceRevision.captured_at.desc(), SourceRevision.source_revision_id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if revision is None:
        raise NoRevisionError(assignment.id)

    targets = await _active_targets(session, revision)
    if not any(target.assignment.id == assignment.id for target in targets):
        raise AssignmentUnreachableError(assignment.id)
    issued = _issue_targets(session, revision, targets, requested={assignment.id})
    logger.info(
        "Manual replication requested",
        extra={
            "info_item_rep_spec_id": str(assignment.id),
            "source_revision_id": str(revision.source_revision_id),
            "issued": bool(issued),
        },
    )
    return issued[0] if issued else None


def _issue_targets(
    session: AsyncSession,
    revision: SourceRevision,
    targets: list[_Target],
    *,
    requested: set,
) -> list[ReplicationCommand]:
    """Run the issuance pipeline over *targets*, publishing only for *requested*.

    ``targets`` is the **collision domain** — every active assignment reachable
    from this revision — while ``requested`` is what the caller actually wants
    issued. They are the same set for the automatic path and differ only for a
    manual re-issue, which must still see a sibling's destination to know its own
    is ambiguous. Nothing outside ``requested`` is written, skips included: a
    sibling that cannot render is not this occasion's business.
    """
    # Every caller guarantees a non-empty intersection: ``issue_for_revision``
    # passes every target's id, and ``issue_for_assignment`` raises
    # AssignmentUnreachableError first. A silent empty return here would be the
    # very ambiguity CR #31 removed one layer up, so there is none (CR #38).
    wanted = [t for t in targets if t.assignment.id in requested]

    blob_skip = _blob_skip_reason(revision)
    if blob_skip is not None:
        _record_skips(session, revision, wanted, blob_skip)
        logger.warning(
            "Revision cannot be replicated: %s",
            blob_skip,
            extra={
                "source_revision_id": str(revision.source_revision_id),
                "assignments": len(wanted),
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
            # Only a *requested* target gets a skip row, and only a requested
            # target gets a WARNING: a log line with no state behind it is the
            # thing the skip rows exist to eliminate, and on the manual path a
            # sibling's broken template would emit one on every click (CR #30).
            wanted_target = target.assignment.id in requested
            if wanted_target:
                _record_skips(session, revision, [target], SKIP_UNRENDERABLE, detail=str(e))
            logger.log(
                logging.WARNING if wanted_target else logging.DEBUG,
                "Assignment cannot render a destination; skipping replication",
                extra={
                    "info_item_rep_spec_id": str(target.assignment.id),
                    "source_revision_id": str(revision.source_revision_id),
                    "error": str(e),
                },
            )
            continue
        renderable.append(target)

    # Publishing a colliding pair would return as destination_conflict, which
    # reports a conflict rather than the path-design error it is — and which of
    # two identical destinations is "the right one" is not a question this
    # service can answer. Only the colliding assignments are refused: they fail,
    # retry and complete independently, which is MUST-1's argument for one
    # command per assignment rather than one carrying a list (CR #11).
    collisions = find_collisions(rendered)
    colliding_keys = {key for keys in collisions.values() for key in keys}
    if collisions:
        _record_skips(
            session,
            revision,
            [
                t
                for t in renderable
                if str(t.assignment.id) in colliding_keys and t.assignment.id in requested
            ],
            SKIP_DESTINATION_COLLISION,
            detail="; ".join(
                f"{destination!r} rendered by {', '.join(keys)}"
                for destination, keys in sorted(collisions.items())
            ),
        )
        logger.error(
            "Assignments render the same destination; skipping those assignments",
            extra={
                "source_revision_id": str(revision.source_revision_id),
                "collisions": {d: list(keys) for d, keys in collisions.items()},
            },
        )

    issued: list[ReplicationCommand] = []
    for target in renderable:
        if target.assignment.id not in requested or str(target.assignment.id) in colliding_keys:
            continue
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
            blob_uri=revision.content_cache_uri,
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
