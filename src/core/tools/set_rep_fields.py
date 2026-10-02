"""set_rep_fields — replace an InfoItem's rep_fields bag, validated (archiver#302).

The only post-create writer of ``rep_fields``: ``PUT /info-items/{id}/rep-fields``
and the dashboard save both call it. Assignment approves a bag against a spec
once; before #302 nothing stopped a later save from dropping a key the spec
requires, and every occasion after it became an ``unrenderable`` skip.

In order, under the InfoItem row lock (``rep_fields_gate``):

1. the v1 shape; a malformed bag is refused before anything is probed with it
2. every active assignment through the gate, collecting *all* refusals so the
   author fixes the bag once rather than once per assignment
3. every active assignment's path, rendered from the old bag and the new one
   against one occasion: a valid edit can still move each later occasion to a
   new path in a permanent public bucket, so it is refused unless the caller
   says the move is meant

Nothing is announced: ``rep_fields`` rides no bus stream.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.core.logging import get_logger
from src.core.models import InfoItem, InfoItemRepSpec, RepSpec
from src.core.rep_fields_schema.validator import ValidationError, validate_rep_fields
from src.core.replication.destination import probe_destination
from src.core.replication.errors import ReplicationRenderError
from src.core.tools.assign_rep_spec import InfoItemNotFoundError
from src.core.tools.rep_fields_gate import check_bag_against_spec, lock_info_item

logger = get_logger(__name__)

CODE_INVALID = "rep_fields_invalid"
CODE_INCOMPLETE = "rep_fields_incomplete"
CODE_UNRENDERABLE = "rep_fields_unrenderable"
CODE_MOVES_DESTINATION = "rep_fields_moves_destination"


@dataclass(frozen=True, slots=True)
class AssignmentRefusal:
    """One active assignment the new bag cannot serve, and why.

    ``errors`` paths point into the bag (``/org/title_slug``); an unrenderable
    refusal has one error with an empty path, since the reason names the key.
    """

    assignment_id: ULID
    rep_spec_id: ULID
    rep_spec_name: str
    code: str
    errors: list[ValidationError]


@dataclass(frozen=True, slots=True)
class DestinationMove:
    """One active assignment whose rendered path the new bag changes."""

    assignment_id: ULID
    rep_spec_id: ULID
    rep_spec_name: str
    before: str
    after: str


class RepFieldsWriteError(Exception):
    """Base class for set_rep_fields refusals. The stored bag is unchanged."""


class RepFieldsInvalidError(RepFieldsWriteError):
    """The bag is not v1-shaped (``src/core/rep_fields_schema/v1.json``)."""

    def __init__(self, errors: list[ValidationError]) -> None:
        self.errors = errors
        super().__init__(f"rep_fields failed schema validation: {errors}")


class RepFieldsRefusedError(RepFieldsWriteError):
    """The bag would break one or more active assignments."""

    def __init__(self, refusals: list[AssignmentRefusal]) -> None:
        self.refusals = refusals
        names = ", ".join(r.rep_spec_name for r in refusals)
        super().__init__(f"rep_fields would break active assignments: {names}")


class RepFieldsMoveError(RepFieldsWriteError):
    """The bag is valid but moves where active assignments render, and that was not allowed."""

    def __init__(self, moves: list[DestinationMove]) -> None:
        self.moves = moves
        names = ", ".join(m.rep_spec_name for m in moves)
        super().__init__(f"rep_fields would move the destination of: {names}")


async def set_rep_fields(
    db: AsyncSession,
    *,
    info_item_id: ULID,
    rep_fields: dict,
    allow_destination_change: bool = False,
) -> InfoItem:
    """Replace the item's whole bag after checking it against every active assignment.

    Flushes, does not commit: the caller owns the transaction.

    Raises:
        InfoItemNotFoundError: no such item.
        RepFieldsInvalidError: the bag is not v1-shaped.
        RepFieldsRefusedError: the bag breaks an active assignment.
        RepFieldsMoveError: the bag moves an active assignment's destination and
            ``allow_destination_change`` is false.
    """
    item = await lock_info_item(db, info_item_id)
    if item is None:
        raise InfoItemNotFoundError(str(info_item_id))

    ok, errors = validate_rep_fields(rep_fields)
    if not ok:
        raise RepFieldsInvalidError(errors)

    assignments = (
        await db.execute(
            select(InfoItemRepSpec, RepSpec)
            .join(RepSpec, RepSpec.rep_spec_id == InfoItemRepSpec.rep_spec_id)
            .where(
                InfoItemRepSpec.info_item_id == info_item_id,
                InfoItemRepSpec.deactivated_at.is_(None),
            )
            .order_by(InfoItemRepSpec.id)
        )
    ).all()

    refusals = [
        refusal
        for assignment, spec in assignments
        if (refusal := _refusal(assignment, spec, rep_fields)) is not None
    ]
    if refusals:
        raise RepFieldsRefusedError(refusals)

    moves = _moves(assignments, item.rep_fields or {}, rep_fields)
    if moves and not allow_destination_change:
        raise RepFieldsMoveError(moves)

    item.rep_fields = rep_fields
    await db.flush()
    if moves:
        logger.warning(
            "rep_fields save moved assignment destinations",
            extra={
                "info_item_id": str(info_item_id),
                "moves": [
                    {"assignment_id": str(m.assignment_id), "before": m.before, "after": m.after}
                    for m in moves
                ],
            },
        )
    return item


def _refusal(assignment: InfoItemRepSpec, spec: RepSpec, bag: dict) -> AssignmentRefusal | None:
    check = check_bag_against_spec(bag, spec.document or {})
    if check.ok:
        return None
    if check.missing:
        code, errors = CODE_INCOMPLETE, check.missing
    else:
        code, errors = CODE_UNRENDERABLE, [{"path": "", "message": check.unrenderable or ""}]
    return AssignmentRefusal(
        assignment_id=assignment.id,
        rep_spec_id=spec.rep_spec_id,
        rep_spec_name=spec.name,
        code=code,
        errors=errors,
    )


def _moves(assignments: list, old_bag: dict, new_bag: dict) -> list[DestinationMove]:
    """Assignments whose path differs between the bags, rendered for one occasion.

    An old bag that could not render is no move: no path came from it to move.
    """
    if old_bag == new_bag:
        return []
    when = datetime.now(UTC)
    moves: list[DestinationMove] = []
    for assignment, spec in assignments:
        document = spec.document or {}
        try:
            before = probe_destination(document, old_bag, captured_at=when)
        except ReplicationRenderError:
            continue
        after = probe_destination(document, new_bag, captured_at=when)
        if before is not None and before != after:
            moves.append(
                DestinationMove(
                    assignment_id=assignment.id,
                    rep_spec_id=spec.rep_spec_id,
                    rep_spec_name=spec.name,
                    before=before,
                    after=after or "",
                )
            )
    return moves
