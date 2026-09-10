"""The SourceRevision write path — one implementation, two callers.

``POST /source-revisions`` and the ``content.revisions`` consumer
(``src.core.changes.consumer``) both land a captured revision. archiver#139
requires the bus path's ``source_revision_captured`` payloads to be *identical*
to the HTTP path's; that is a property of there being one path, not of two paths
being carefully kept in step, so the write lives here and both callers delegate.

The extraction is deliberately behaviour-preserving: idempotency on
``(info_source_id, content_fingerprint)`` via ``INSERT … ON CONFLICT DO NOTHING
… RETURNING``, the emit built only on a genuinely new row, and the outbox row
added to the caller's session so it commits with the revision.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from co_core.pure.models.changes import InfoItemBinding, SourceRevisionCapturedEmit
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.core.fingerprints import is_valid_fingerprint
from src.core.logging import get_logger
from src.core.models import ChangesOutboxRow, InfoItemSource, InfoSource, SourceRevision
from src.core.services.replication_issuance import issue_for_revision
from src.core.spec_match import (
    NOT_COMPARED,
    SUPERSEDED,
    SpecComparison,
    compare_spec_fingerprint,
)

logger = get_logger(__name__)

CHANGE_STREAM_TOPIC = "info.changes"


class SourceRevisionWriteError(Exception):
    """Base for domain failures of the SourceRevision write path.

    Transport-agnostic on purpose: the route maps these to an error envelope, the
    consumer maps them to a log line and an ack. Neither mapping belongs in
    ``src/core``.
    """


class UnknownInfoSourceError(SourceRevisionWriteError):
    """``info_source_id`` does not reference a known InfoSource.

    A 404 over HTTP. On the bus it is ack-and-drop: the registry is the authority
    on what exists, so an observation naming something it does not hold is not a
    revision it can record (archiver#139).
    """

    def __init__(self, info_source_id: ULID) -> None:
        super().__init__(f"info_source not found: {info_source_id}")
        self.info_source_id = info_source_id


class InvalidFingerprintError(SourceRevisionWriteError):
    """The fingerprint is not spelled ``sha256:<64 lowercase hex>``.

    A 422 over HTTP (caught earlier, at the Pydantic layer). On the bus it is
    poison: redelivery produces the identical value, so it is quarantined rather
    than retried.
    """

    def __init__(self, value: str) -> None:
        super().__init__(f"fingerprint must match 'sha256:<64 lowercase hex>': {value!r}")
        self.value = value


class InvalidInfoSourceIdError(SourceRevisionWriteError):
    """``info_source_id`` is not a ULID.

    Distinct from ``UnknownInfoSourceError``: that one is a well-formed id for
    something the registry does not hold (drop it), this one cannot identify
    anything at all (quarantine it).
    """

    def __init__(self, value: str) -> None:
        super().__init__(f"info_source_id is not a valid ULID: {value!r}")
        self.value = value


class SourceRevisionIdConflictError(SourceRevisionWriteError):
    """A caller-supplied ``source_revision_id`` is taken by a different pair.

    Only reachable from the HTTP path — Archiver allocates the id on the bus path
    (cannobserv#301), so the consumer never supplies one and this cannot fire
    there.
    """

    def __init__(self, existing: SourceRevision) -> None:
        super().__init__(
            "source_revision_id already in use for a different "
            "(info_source_id, content_fingerprint) pair"
        )
        self.existing = existing


@dataclass(frozen=True, slots=True)
class RevisionFacts:
    """What a caller knows about one captured revision.

    Named for what it is on the bus — an observation the registry decides to
    record — rather than for either transport. The optional fields are exactly
    those a producer may not hold.

    ``content_cache_uri`` / ``content_cache_expires_at`` are **not durable
    storage**: on the bus path they carry Replicator's temp-store blob
    (``gs://co-gcs-blobs`` since 2026-08-20; a VM-local ``file://`` before) and
    its expiry horizon, which is a cache with a TTL clock the registry does not
    control — it runs from the blob's *last reference*, so a re-observation may
    carry a later horizon for the same bytes (archiver#201). Durable bytes are
    what RepSpec replication is for.
    """

    info_source_id: ULID
    content_fingerprint: str
    captured_at: datetime
    content_size_bytes: int | None = None
    content_media_type: str | None = None
    content_cache_uri: str | None = None
    content_cache_expires_at: datetime | None = None
    # Observation provenance — the bus path holds these, the HTTP path never
    # does. See the column comments in src/core/models/source_revision.py for
    # why each is recorded and why spec_fingerprint is not enforced.
    source_media_type: str | None = None
    spec_fingerprint: str | None = None
    command_id: str | None = None
    source_revision_id: ULID | None = None


def validate_fingerprint(value: str) -> str:
    """Return ``value`` if it is a well-formed content fingerprint.

    The bus path leans on this where the HTTP path leans on Pydantic: Archiver's
    uniqueness key is ``(info_source_id, content_fingerprint)``, so a
    differently-spelled fingerprint for identical content is a silent duplicate
    row rather than a loud failure.

    Raises:
        InvalidFingerprintError: it is not.
    """
    if not is_valid_fingerprint(value):
        raise InvalidFingerprintError(value)
    return value


def parse_info_source_id(value: str) -> ULID:
    """Parse a wire ``info_source_id`` into a ULID.

    Raises:
        InvalidInfoSourceIdError: it is not a ULID.
    """
    try:
        return ULID.from_str(value)
    except ValueError as e:
        raise InvalidInfoSourceIdError(value) from e


async def record_revision(
    session: AsyncSession, facts: RevisionFacts
) -> tuple[SourceRevision, bool]:
    """Record a captured revision, emitting ``source_revision_captured`` if new.

    Returns ``(row, inserted)``. ``inserted`` is ``False`` for the idempotent
    no-op — the same ``(info_source_id, content_fingerprint)`` pair already
    exists — in which case the existing row is returned and **no** outbox event
    is written. That is what makes at-least-once bus redelivery and a re-POST
    the same operation.

    Does not commit: the outbox row is added to ``session`` so it lands in the
    caller's transaction alongside the revision.

    Raises:
        UnknownInfoSourceError: ``info_source_id`` is not in the registry.
        SourceRevisionIdConflictError: a supplied ``source_revision_id`` belongs
            to a different pair.
    """
    source = await session.get(InfoSource, facts.info_source_id)
    if source is None:
        raise UnknownInfoSourceError(facts.info_source_id)

    # Reject ULID collisions against a *different* (source, fingerprint). An id
    # supplied for its own existing pair falls through to the ON CONFLICT path
    # below and returns that row unchanged.
    if facts.source_revision_id is not None:
        clashing = await session.get(SourceRevision, facts.source_revision_id)
        if clashing is not None and (
            clashing.info_source_id != facts.info_source_id
            or clashing.content_fingerprint != facts.content_fingerprint
        ):
            raise SourceRevisionIdConflictError(clashing)

    # Compare the observed spec_fingerprint against the specs the registry
    # actually holds (cannobserv#309). Skipped outright when nothing was
    # reported, so the HTTP write path — which never carries a fingerprint —
    # does not pay to build an index it will discard (CR round 3, finding 22).
    # It lives here rather than in the consumer so there is one answer per
    # revision regardless of which path wrote it.
    comparison = (
        compare_spec_fingerprint(facts.spec_fingerprint, source.source_specs)
        if facts.spec_fingerprint is not None
        else NOT_COMPARED
    )

    insert_values: dict = {
        "info_source_id": facts.info_source_id,
        "content_fingerprint": facts.content_fingerprint,
        "captured_at": facts.captured_at,
        "content_size_bytes": facts.content_size_bytes,
        "content_media_type": facts.content_media_type,
        "content_cache_uri": facts.content_cache_uri,
        "content_cache_expires_at": facts.content_cache_expires_at,
        "source_media_type": facts.source_media_type,
        "spec_fingerprint": facts.spec_fingerprint,
        "spec_match": comparison.match,
        "spec_position": comparison.position,
        "command_id": facts.command_id,
    }
    if facts.source_revision_id is not None:
        insert_values["source_revision_id"] = facts.source_revision_id

    stmt = (
        pg_insert(SourceRevision)
        .values(**insert_values)
        .on_conflict_do_nothing(index_elements=["info_source_id", "content_fingerprint"])
        .returning(SourceRevision)
    )
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    inserted = row is not None

    if row is None:
        existing = await session.execute(
            select(SourceRevision).where(
                SourceRevision.info_source_id == facts.info_source_id,
                SourceRevision.content_fingerprint == facts.content_fingerprint,
            )
        )
        row = existing.scalar_one()

    if inserted:
        _log_spec_comparison(facts, comparison)
        session.add(
            ChangesOutboxRow(
                topic=CHANGE_STREAM_TOPIC,
                payload=(await _captured_emit(session, row)).model_dump(mode="json"),
            )
        )
        # Replication rides the same transaction (archiver#169). Under the
        # idempotent no-op it deliberately does not run: a redelivery is the
        # same occasion, and a second command_id for it is exactly the
        # re-replication MUST-1 reserves for a genuinely new one.
        await issue_for_revision(session, row)
    else:
        _refresh_spec_comparison(row, facts, comparison)
        _refresh_cache_reference(row, facts)

    return row, inserted


def _refresh_cache_reference(row: SourceRevision, facts: RevisionFacts) -> None:
    """Carry a re-observation's blob reference onto an existing row (archiver#201).

    The idempotent no-op returns the row the *first* observation wrote, and its
    cache columns describe the blob as it stood then. Replicator's TTL runs from
    the blob's **last reference** (the fetch issuer contract's MUST-7), so every
    full re-fetch of unchanged bytes re-announces a later ``blob_expires_at`` —
    and a row that keeps the first horizon reports the blob expired while it is
    still there. ``_blob_skip_reason`` then refuses a replication the consumer
    would have served, and for a *stable* item nothing corrects it: no later
    revision ever arrives to carry the fresher horizon. The 2026-08-20 backend
    flip is the same defect from the other side — a row keeps a dead ``file://``
    URI after a re-observation offered the ``gs://`` one.

    Same shape as ``_refresh_spec_comparison``: the most recent observation
    wins, the two columns move as a unit (a URI without its horizon is a
    reference to bytes that may already be gone), and no outbox event is written
    because the revision's identity is unchanged. Two guards keep at-least-once
    delivery from regressing it:

    - **An absent reference never erases a stored one.** The HTTP path carries
      no blob, and a fact without one has nothing newer to say.
    - **The horizon only moves forward.** A redelivered *older* observation
      carries an earlier ``blob_expires_at`` and is ignored; an equal one is the
      same emission and a no-op. An unknown incoming horizon cannot be ordered
      against a known one and is ignored too — ``None`` records absence, never
      a guess (docs/BUS.md) — while a known one does replace an unknown.

    Mutates ``row`` in the caller's session; the caller's commit persists it.
    """
    if facts.content_cache_uri is None:
        return
    stored_at = row.content_cache_expires_at
    offered_at = facts.content_cache_expires_at
    if row.content_cache_uri is not None:
        if offered_at is None:
            return
        if stored_at is not None and offered_at <= stored_at:
            return
    logger.info(
        "Refreshed revision blob reference from a re-observation",
        extra={
            "source_revision_id": str(row.source_revision_id),
            "content_cache_expires_at": offered_at.isoformat() if offered_at else None,
            "previous_expires_at": stored_at.isoformat() if stored_at else None,
        },
    )
    row.content_cache_uri = facts.content_cache_uri
    row.content_cache_expires_at = offered_at


def _refresh_spec_comparison(
    row: SourceRevision, facts: RevisionFacts, comparison: SpecComparison
) -> None:
    """Carry a re-observation's spec verdict onto an existing row.

    The idempotent no-op returns the row the *first* observation wrote, and its
    spec columns describe the comparison made then. Left alone that is a
    diagnostic column asserting something false: move the registry to a new spec,
    re-observe content already recorded, and the row keeps claiming ``current``
    for a spec we no longer hold — while the observation that would have flagged
    it leaves no trace. Worse, that is the *stuck producer* case, which is the one
    this column exists to detect (CR round 3, finding 21).

    So the verdict is refreshed to the most recent observation's. The three
    columns move as a unit — a ``spec_match`` describing a different
    ``spec_fingerprint`` than the one stored is internally inconsistent, which is
    worse than either being stale. No outbox event: the revision's identity is
    ``(info_source_id, content_fingerprint)`` and neither changed, so subscribers
    have nothing new to learn.

    Mutates ``row`` in the caller's session; the caller's commit persists it.
    """
    if facts.spec_fingerprint is None:
        # Nothing was reported, so there is no newer verdict — and blanking the
        # stored one would let a re-POST through the HTTP path (which never
        # carries a fingerprint) erase what the bus path recorded.
        return
    if (row.spec_fingerprint, row.spec_match, row.spec_position) == (
        facts.spec_fingerprint,
        comparison.match,
        comparison.position,
    ):
        # The common case: an at-least-once redelivery of the same observation.
        # Returning here is what keeps a redelivery from re-logging the flag.
        return

    row.spec_fingerprint = facts.spec_fingerprint
    row.spec_match = comparison.match
    row.spec_position = comparison.position
    _log_spec_comparison(facts, comparison)


def _log_spec_comparison(facts: RevisionFacts, comparison: SpecComparison) -> None:
    """Log the two conditions worth an operator's attention.

    Called on insert and on a *change* of verdict, never on an unchanged
    redelivery — the flag should fire once per state transition, not once per
    delivery. The publisher throttles its repeated conditions for the same reason
    (``ERROR_LOG_EVERY``); here the state itself is the natural throttle.
    """
    if comparison.match == SUPERSEDED:
        # Not a rejection: archiver#140 makes spec delivery eventually
        # consistent, so this is an expected transient state whose revision is
        # real — but a *persistent* one means the producer's cached spec never
        # caught up, and nothing else would report that.
        logger.warning(
            "Revision extracted under a spec this InfoSource no longer holds",
            extra={
                "info_source_id": str(facts.info_source_id),
                "spec_fingerprint": facts.spec_fingerprint,
                "content_fingerprint": facts.content_fingerprint,
            },
        )
    elif comparison.is_fallback:
        # Selector rot in progress: the primary spec stopped matching and the
        # producer fell through to a cross-check alternative.
        logger.warning(
            "Revision extracted under a fallback spec, not the primary",
            extra={
                "info_source_id": str(facts.info_source_id),
                "spec_position": comparison.position,
                "content_fingerprint": facts.content_fingerprint,
            },
        )


async def _captured_emit(session: AsyncSession, row: SourceRevision) -> SourceRevisionCapturedEmit:
    """Build the ``source_revision_captured`` event for a newly-inserted row.

    Bindings are ordered by ``info_item_id`` so the emitted list is deterministic
    — downstream consumers diffing payloads (snapshot tests among them) rely on
    stable ordering.
    """
    bindings_result = await session.execute(
        select(InfoItemSource.info_item_id)
        .where(
            InfoItemSource.info_source_id == row.info_source_id,
            InfoItemSource.deactivated_at.is_(None),
        )
        .order_by(InfoItemSource.info_item_id)
    )
    return SourceRevisionCapturedEmit(
        occurred_at=datetime.now(UTC),
        info_source_id=str(row.info_source_id),
        source_revision_id=str(row.source_revision_id),
        content_fingerprint=row.content_fingerprint,
        bindings=[InfoItemBinding(info_item_id=str(iid)) for (iid,) in bindings_result.all()],
    )
