"""assign_rep_spec — bind a RepSpec to an InfoItem with effective dating."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.core.models import InfoItemRepSpec, RepSpec
from src.core.tools.rep_fields_gate import check_bag_against_spec, lock_info_item


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


class RepFieldsUnrenderableError(AssignmentError):
    """rep_fields satisfies required_fields but cannot produce a destination.

    Presence is a weaker statement than renderability: ``"WA LCB"`` is present
    and non-null, and is not a path segment. Refusing here rather than at
    replication time is the point — ``document`` freezes on assignment (#83), so
    this is the last moment an author can fix either side (archiver#168 CR #5).
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"rep_fields cannot render this RepSpec's path_template: {reason}")


class DuplicateAssignmentError(AssignmentError):
    """The RepSpec is already actively assigned to this InfoItem.

    Both rows would render one destination, and issuance skips both as
    ``destination_collision`` on every occasion (archiver#301). Backed by the
    ``uq_iirs_item_spec_active`` partial unique index.
    """

    def __init__(self, existing_assignment_id: ULID) -> None:
        self.existing_assignment_id = existing_assignment_id
        super().__init__(f"already actively assigned as {existing_assignment_id!s}")


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
    - the RepSpec is not already actively assigned to this InfoItem
    - the InfoItem.rep_fields satisfies the RepSpec.document.required_fields list
      and renders its path_template (per src.core.tools.rep_fields_gate)

    On success returns the persisted assignment row (active, public_url=None).
    Caller is responsible for committing the session.
    """
    # FOR UPDATE, and before the RepSpec lock (item → spec, the order every
    # writer takes): serializes against set_rep_fields, which checks this
    # item's active assignments under the same lock. Without it a save and this
    # assign each pass on their own snapshot and both commit (archiver#302).
    item = await lock_info_item(db, info_item_id)
    if item is None:
        raise InfoItemNotFoundError(str(info_item_id))

    # FOR UPDATE: serializes against update_rep_spec's draft gate, which takes
    # the same lock. Creating this assignment is what flips the RepSpec out of
    # draft state, so the two must not interleave (archiver#83 CR).
    spec = await db.get(RepSpec, rep_spec_id, with_for_update=True)
    if spec is None:
        raise RepSpecNotFoundError(str(rep_spec_id))

    # Race-free under the spec lock above: a concurrent assign of this spec
    # waits on it, then sees this row once we commit.
    existing_id = await db.scalar(
        select(InfoItemRepSpec.id).where(
            InfoItemRepSpec.info_item_id == info_item_id,
            InfoItemRepSpec.rep_spec_id == rep_spec_id,
            InfoItemRepSpec.deactivated_at.is_(None),
        )
    )
    if existing_id is not None:
        raise DuplicateAssignmentError(existing_id)

    # Presence is not renderability, and this is the last synchronous chance to
    # say so (archiver#168 CR #5): the gate checks both.
    check = check_bag_against_spec(item.rep_fields or {}, spec.document or {}, org=None)
    if check.missing:
        raise RepFieldsIncompleteError(check.missing)
    if check.unrenderable is not None:
        raise RepFieldsUnrenderableError(check.unrenderable)

    assignment = InfoItemRepSpec(
        info_item_id=info_item_id,
        rep_spec_id=rep_spec_id,
        activated_at=activated_at or datetime.now(UTC),
    )
    db.add(assignment)
    await db.flush()
    return assignment
