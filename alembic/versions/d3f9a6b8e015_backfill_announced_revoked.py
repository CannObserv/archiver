"""backfill info_items.announced_revoked from the snapshot's tombstone rule

Revision ID: d3f9a6b8e015
Revises: b7e2d94c1a38
Create Date: 2026-09-30 22:05:00.000000

archiver#293 - ``b7e2d94c1a38`` adds the column ``false`` everywhere, which is
wrong for every row whose last announcement was a tombstone. Left there, the
next binding mutation that keeps one of them unannounceable would tombstone it
once more - the churn the column exists to stop.

**Scope is the snapshot's own revoked rule**, so the flag and the full set
agree from the first deploy: ``announcement_generation > 0`` and no active
binding to a source with a non-empty ``source_specs`` array. A generation-0 row
has announced nothing and stays ``false``; a live row's last announcement was
live and stays ``false``.

``CASE`` guards ``jsonb_array_length``, which *errors* on a non-array: Postgres
does not promise ``AND`` evaluates left to right, so ``jsonb_typeof(...) =
'array' AND jsonb_array_length(...) > 0`` is not a guard.

Idempotent: the predicate reads only state the upgrade does not write. Downgrade
is a no-op - dropping the column in ``b7e2d94c1a38``'s downgrade removes the
flags anyway.
"""

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d3f9a6b8e015"
down_revision: str | Sequence[str] | None = "b7e2d94c1a38"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.runtime.migration")


def upgrade() -> None:
    """Mark every announced, currently unannounceable row as revoked."""
    result = op.get_bind().execute(
        sa.text(
            "UPDATE information.info_items"
            "   SET announced_revoked = true"
            " WHERE announcement_generation > 0"
            "   AND NOT announced_revoked"
            "   AND NOT EXISTS ("
            "         SELECT 1"
            "           FROM information.info_item_sources iis"
            "           JOIN information.info_sources s"
            "             ON s.info_source_id = iis.info_source_id"
            "          WHERE iis.info_item_id = info_items.info_item_id"
            "            AND iis.deactivated_at IS NULL"
            "            AND CASE WHEN jsonb_typeof(s.source_specs) = 'array'"
            "                     THEN jsonb_array_length(s.source_specs) > 0"
            "                     ELSE false END"
            "       )"
        )
    )
    logger.info(
        "archiver#293: marked %s InfoItem(s) announced_revoked; "
        "binding mutations on them no longer re-tombstone",
        result.rowcount,
    )


def downgrade() -> None:
    """No-op: ``b7e2d94c1a38``'s downgrade drops the column."""
