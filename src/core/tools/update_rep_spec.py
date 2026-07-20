"""update_rep_spec — tiered in-place edit of an existing RepSpec.

RepSpecs are *not* freely mutable. ``InfoItemRepSpec`` is effective-dated, so an
assignment row asserts "item X replicated under spec R from T1 to T2, producing
the artefact at public_url". Rewriting the document of an assigned spec makes
that assertion unverifiable — the artefact in the provider bucket was written
under the old ``path_template`` and nothing records what it was.

The contract (archiver#83; see
docs/plans/2026-07-20-83-rep-spec-document-editing-adr.md):

- tier 1 — ``name`` is always mutable. It is a label with no replication
  semantics.
- tier 2 — ``document`` is mutable only while the RepSpec is a *draft*: zero
  ``info_item_rep_specs`` rows, active **or** deactivated. A deactivated
  assignment still means a replication run happened under that document.
- tier 3 — an assigned RepSpec is frozen. Clone it and migrate the assignments
  instead (archiver#95, deferred until Replicator consumes documents).

``provider`` is frozen in every tier, drafts included. It lives both as a column
and as a document key that must agree; freezing it removes an invariant rather
than adding a consistency check.

Document updates are whole-document *replacement*, matching
``update_info_source_specs``. Merge semantics cannot express key removal, which
would make ``object_options`` entries unremovable under the envelope's
``additionalProperties: false``.

Caller is responsible for committing the session.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.core.models import InfoItemRepSpec, RepSpec
from src.core.rep_spec_schema.validator import ValidationError, validate_rep_spec


class UpdateRepSpecError(Exception):
    """Base class for update_rep_spec failures."""


class RepSpecNotFoundError(UpdateRepSpecError):
    """The given rep_spec_id does not reference a RepSpec."""


class InvalidRepSpecError(UpdateRepSpecError):
    """The replacement document failed validation, or attempted a provider change."""

    def __init__(self, errors: list[ValidationError]) -> None:
        self.errors = errors
        super().__init__(f"invalid rep_spec: {errors}")


class RepSpecNotDraftError(UpdateRepSpecError):
    """A document edit was attempted on a RepSpec that has been assigned.

    ``assignment_count`` counts all assignment rows, active and deactivated, so
    callers can report the blast radius they are being protected from.
    """

    def __init__(self, rep_spec_id: ULID, assignment_count: int) -> None:
        self.rep_spec_id = rep_spec_id
        self.assignment_count = assignment_count
        super().__init__(
            f"RepSpec {rep_spec_id} has {assignment_count} assignment(s); "
            "document is frozen once assigned"
        )


async def assignment_count(db: AsyncSession, rep_spec_id: ULID) -> int:
    """Count *all* assignment rows for a RepSpec — active and deactivated.

    The draft gate deliberately does not filter on ``deactivated_at IS NULL``:
    a deactivated assignment still means a replication run happened under the
    current document.
    """
    stmt = (
        select(func.count())
        .select_from(InfoItemRepSpec)
        .where(InfoItemRepSpec.rep_spec_id == rep_spec_id)
    )
    return int((await db.execute(stmt)).scalar_one())


async def update_rep_spec(
    db: AsyncSession,
    *,
    rep_spec_id: ULID,
    name: str | None = None,
    document: dict | None = None,
) -> RepSpec:
    """Update a RepSpec's name and/or document, enforcing the tiered contract.

    Omitted arguments are left untouched; omitting both is a no-op that does not
    stamp ``updated_at``. Validation runs before any mutation, so a rejected
    document leaves the row exactly as it was.

    Raises ``RepSpecNotFoundError``, ``InvalidRepSpecError``, or
    ``RepSpecNotDraftError``.
    """
    spec = await db.get(RepSpec, rep_spec_id)
    if spec is None:
        raise RepSpecNotFoundError(str(rep_spec_id))

    if document is not None:
        count = await assignment_count(db, rep_spec_id)
        if count:
            raise RepSpecNotDraftError(rep_spec_id, count)

        errors: list[ValidationError] = []

        doc_provider = document.get("provider")
        if doc_provider is not None and doc_provider != spec.provider:
            errors.append(
                {
                    "path": "/provider",
                    "message": (
                        f"provider is immutable: RepSpec is {spec.provider!r}, "
                        f"document.provider is {doc_provider!r}"
                    ),
                }
            )

        ok, schema_errors = validate_rep_spec(document)
        if not ok:
            errors.extend(schema_errors)

        if errors:
            raise InvalidRepSpecError(errors)

    changed = False
    if name is not None and name != spec.name:
        spec.name = name
        changed = True
    if document is not None and document != spec.document:
        spec.document = dict(document)
        changed = True

    if changed:
        spec.updated_at = datetime.now(UTC)

    await db.flush()
    return spec
