"""assign_rep_spec — bind a RepSpec to an InfoItem with effective dating."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.core.models import InfoItem, InfoItemRepSpec, RepSpec
from src.core.rep_fields_schema.validator import validate_rep_fields_against_spec


class AssignmentError(Exception):
    """Base class for assign_rep_spec failures."""


class InfoItemNotFoundError(AssignmentError):
    """The given info_item_id does not exist."""


class RepSpecNotFoundError(AssignmentError):
    """The given rep_spec_id does not exist."""


class RepFieldsIncompleteError(AssignmentError):
    """The InfoItem.rep_fields does not satisfy the RepSpec's required_fields."""

    def __init__(self, missing: list[dict]) -> None:
        self.missing = missing
        super().__init__(f"rep_fields incomplete: {missing}")


async def lock_rep_specs(
    db: AsyncSession,
    rep_spec_ids: list[str],
) -> dict[str, RepSpec]:
    """Lock the given RepSpec rows ``FOR UPDATE`` and return them keyed by ULID string.

    For callers that create ``InfoItemRepSpec`` rows directly instead of going
    through :func:`assign_rep_spec` — notably the atomic ``POST /info-items``
    path, which needs the rows for ``required_fields`` validation anyway. Taking
    the same lock keeps them serialized against ``update_rep_spec``'s draft gate
    (archiver#83 CR).

    IDs are deduplicated and locked in sorted order so two concurrent callers
    naming the same specs in different request order cannot deadlock. Unknown
    IDs are simply absent from the result — callers raise their own 404s.
    """
    if not rep_spec_ids:
        return {}

    ordered = sorted({str(rid) for rid in rep_spec_ids})
    stmt = (
        select(RepSpec)
        .where(RepSpec.rep_spec_id.in_(ordered))
        .order_by(RepSpec.rep_spec_id)
        .with_for_update()
    )
    rows = (await db.execute(stmt)).scalars().all()
    return {str(row.rep_spec_id): row for row in rows}


async def assign_rep_spec(
    db: AsyncSession,
    *,
    info_item_id: ULID,
    rep_spec_id: ULID,
    activated_at: datetime | None = None,
) -> InfoItemRepSpec:
    """Create a new InfoItemRepSpec assignment.

    Validates that:
    - the InfoItem exists
    - the RepSpec exists
    - the InfoItem.rep_fields satisfies the RepSpec.document.required_fields list
      (per src.core.rep_fields_schema.validator.validate_rep_fields_against_spec)

    On success returns the persisted assignment row (active, public_url=None).
    Caller is responsible for committing the session.
    """
    item = await db.get(InfoItem, info_item_id)
    if item is None:
        raise InfoItemNotFoundError(str(info_item_id))

    # FOR UPDATE: serializes against update_rep_spec's draft gate, which takes
    # the same lock. Creating this assignment is what flips the RepSpec out of
    # draft state, so the two must not interleave (archiver#83 CR).
    spec = await db.get(RepSpec, rep_spec_id, with_for_update=True)
    if spec is None:
        raise RepSpecNotFoundError(str(rep_spec_id))

    required_fields = (spec.document or {}).get("required_fields", [])
    ok, errors = validate_rep_fields_against_spec(item.rep_fields or {}, required_fields)
    if not ok:
        raise RepFieldsIncompleteError(errors)

    assignment = InfoItemRepSpec(
        info_item_id=info_item_id,
        rep_spec_id=rep_spec_id,
        activated_at=activated_at or datetime.now(UTC),
    )
    db.add(assignment)
    await db.flush()
    return assignment
