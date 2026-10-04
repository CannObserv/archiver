"""drop ix_iirs_item_active

Revision ID: 7c4e1f2a9b30
Revises: cdeb05831bd7
Create Date: 2026-10-04 00:00:00.000000

archiver#311 - ``uq_iirs_item_spec_active`` (cdeb05831bd7, archiver#301) has
the same ``deactivated_at IS NULL`` predicate as ``ix_iirs_item_active`` and
leads with the same column, so it serves every item-only active lookup. The
older index is write overhead with no reader. The downgrade re-creates it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7c4e1f2a9b30"
down_revision: str | Sequence[str] | None = "cdeb05831bd7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX_NAME = "ix_iirs_item_active"


def upgrade() -> None:
    """Drop the redundant item-only active index."""
    op.drop_index(INDEX_NAME, table_name="info_item_rep_specs", schema="information")


def downgrade() -> None:
    """Re-create the item-only active index."""
    op.create_index(
        INDEX_NAME,
        "info_item_rep_specs",
        ["info_item_id"],
        unique=False,
        schema="information",
        postgresql_where=sa.text("deactivated_at IS NULL"),
    )
