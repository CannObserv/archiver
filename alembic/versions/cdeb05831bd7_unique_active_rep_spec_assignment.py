"""one active assignment per (info_item, rep_spec)

Revision ID: cdeb05831bd7
Revises: d3f9a6b8e015
Create Date: 2026-10-02 15:45:17.097957

archiver#301 - two active ``info_item_rep_specs`` rows for one item and one
spec render the same destination, and ``replication_issuance`` skips **both**
as ``destination_collision`` on every occasion, permanently. Nothing stopped
the second: ``ix_iirs_item_active`` is not unique and ``assign_rep_spec`` did
not check. ``assign_rep_spec`` now refuses; this partial unique index is the
backstop for any writer that bypasses it.

**Pre-check.** ``CREATE UNIQUE INDEX`` over rows that already collide fails
with a bare ``UniqueViolation`` that names neither row. The upgrade looks
first and refuses with every colliding pair, so the operator can deactivate
the extra row (``DELETE /info-items/{id}/rep-spec-assignments/{aid}``) and
re-run. It never picks a survivor itself: which row's ``public_url`` is the
citable one is the operator's call.

``ix_iirs_item_active`` stays for now. This index's leading column serves the
same item-only lookups, so it is redundant; dropping it is archiver#311.
"""

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "cdeb05831bd7"
down_revision: str | Sequence[str] | None = "d3f9a6b8e015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.runtime.migration")

INDEX_NAME = "uq_iirs_item_spec_active"


def upgrade() -> None:
    """Refuse on existing duplicates, else add the partial unique index."""
    duplicates = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT info_item_id, rep_spec_id, string_agg(id, ', ' ORDER BY id)"
                "  FROM information.info_item_rep_specs"
                " WHERE deactivated_at IS NULL"
                " GROUP BY info_item_id, rep_spec_id"
                " HAVING count(*) > 1"
                " ORDER BY info_item_id, rep_spec_id"
            )
        )
        .all()
    )
    if duplicates:
        pairs = "; ".join(
            f"info_item {item} / rep_spec {spec}: assignments {ids}"
            for item, spec, ids in duplicates
        )
        raise RuntimeError(
            f"archiver#301: {len(duplicates)} (info_item, rep_spec) pair(s) have more than "
            f"one active assignment - deactivate all but one of each, then re-run: {pairs}"
        )

    op.create_index(
        INDEX_NAME,
        "info_item_rep_specs",
        ["info_item_id", "rep_spec_id"],
        unique=True,
        schema="information",
        postgresql_where=sa.text("deactivated_at IS NULL"),
    )
    logger.info("archiver#301: %s created; no duplicate active assignments found", INDEX_NAME)


def downgrade() -> None:
    """Drop the index; ``assign_rep_spec``'s own check is unaffected."""
    op.drop_index(INDEX_NAME, table_name="info_item_rep_specs", schema="information")
