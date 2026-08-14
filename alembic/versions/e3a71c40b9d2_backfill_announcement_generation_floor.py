"""backfill announcement_generation floor: no announced generation is 0

Revision ID: e3a71c40b9d2
Revises: c81f4a2e7d36
Create Date: 2026-08-14 10:20:00.000000

archiver#161 — generation 0 on the wire makes the return leg's sentinel
ambiguous.

``info.watch-status`` spells "Watcher has never reconciled any announcement"
as ``applied_generation = 0``; the co-core type is ``ge=0``, so 0 is the only
spelling available. If an *announcement* can also carry 0, the wire value
collapses two states — never reconciled, and correctly reconciled at 0 — and
the #151 drift detector (``applied < announced``) reads an unapplied item as
clean. That is the lie-in-the-safe-direction the channel exists to remove.

**Where the zeros come from.** Not the delta path: ``_bump_generation``
increments before the payload is built, so its floor is already 1. Only the
snapshot can read a row that never passed an announce site, and there are two
such populations — rows predating ``f5c522f65657`` (which added the column with
``server_default="0"``), and rows the #150 import classed ``unchanged``, whose
early return skips the announce that would have healed them. Three of Watcher's
four watched items sat at ``applied_generation = 0`` in production on
2026-08-14, reconciled from real snapshot frames.

**Why a backfill and not a producer change.** Every future item passes a bump
site before its first announcement, so the floor holds going forward without
new code. Only the existing corpus needs moving. Consumers need no change:
apply-iff-greater is total over the shift, ``1 > 0`` fires, and the next full
set re-announces every touched key exactly once.

``announced_at`` moves with the counter — it is the drift detector's clock, and
a bumped generation with a NULL stamp would render as drift of unknown age.
The consequence is that a backfilled row's drift age starts at *this migration*
rather than at a real announcement. Correct in the safe direction: it dates the
announcement the next snapshot will actually publish.

Downgrade is a no-op. Nothing distinguishes a backfilled 1 from a genuinely
announced 1, so restoring the zeros would corrupt live rows to un-fix a
consumer ambiguity — strictly worse than leaving the floor in place.
"""

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e3a71c40b9d2"
down_revision: str | Sequence[str] | None = "c81f4a2e7d36"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.runtime.migration")


def upgrade() -> None:
    """Lift every un-bumped generation to 1. Idempotent — a re-run matches nothing."""
    result = op.get_bind().execute(
        sa.text(
            "UPDATE information.info_items"
            "   SET announcement_generation = 1, announced_at = now()"
            " WHERE announcement_generation = 0"
        )
    )
    logger.info(
        "archiver#161: lifted %s InfoItem(s) off generation 0; "
        "the next info.registry full set re-announces them",
        result.rowcount,
    )


def downgrade() -> None:
    """No-op: a backfilled 1 is indistinguishable from an announced 1."""
