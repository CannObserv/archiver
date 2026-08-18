"""Read the current replication state of an assignment (archiver#171).

`#170` gave `info_item_rep_specs.public_url` an automated writer. This is the
other half of #143's requirement — *do not ship a column that silently
populates*: the assignment views render where the URL came from, or why there
is not one yet.

The answer is the **latest occasion**, and "occasion" deliberately includes the
refusals. #169 persists a `state="skipped"` row for every assignment it declined
to publish for, because a refusal that lives only in a log line renders in the
dashboard as "not replicated yet" — indistinguishable from a replication still
in flight, and permanent.

Read-only and commit-free: this is a projection for a template, not a writer.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.core.models import ReplicationCommand


async def latest_commands_by_assignment(
    session: AsyncSession, assignment_ids: Sequence[ULID]
) -> dict[ULID, ReplicationCommand]:
    """The newest occasion per assignment, keyed by ``info_item_rep_spec_id``.

    Assignments with no occasion at all are **absent** rather than mapped to
    ``None``: a template asking ``latest.get(id)`` gets one falsy answer either
    way, and the dict then carries no rows that mean nothing.

    Ordering matches ``_is_newest_occasion``'s — ``issued_at`` then
    ``command_id``, which is ULID-shaped and therefore monotonic within a
    millisecond, so two occasions minted in the same instant still resolve
    deterministically rather than by insertion order.
    """
    if not assignment_ids:
        return {}
    result = await session.execute(
        select(ReplicationCommand)
        .where(ReplicationCommand.info_item_rep_spec_id.in_(list(assignment_ids)))
        .distinct(ReplicationCommand.info_item_rep_spec_id)
        .order_by(
            ReplicationCommand.info_item_rep_spec_id,
            ReplicationCommand.issued_at.desc(),
            ReplicationCommand.command_id.desc(),
        )
    )
    return {command.info_item_rep_spec_id: command for command in result.scalars()}
