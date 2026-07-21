"""drop info_item_source_revisions

Revision ID: 4413805453dd
Revises: 291c95e00110
Create Date: 2026-07-21 15:34:38.009373

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4413805453dd"
down_revision: str | Sequence[str] | None = "291c95e00110"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Drop the info_item_source_revisions pin table (archiver#101).

    The per-item revision pin table served two now-dissolved purposes: an
    automatic content timeline (never wired — post-#185 Watcher writes
    source_revisions, not pins) and explicit revision pinning (zero automatic
    writers, zero consumers). The item's content timeline is a query over its
    InfoSource bindings. No downstream reader depends on this table.
    """
    # Dropping the table cascades its index (ix_iisr_item_bound_desc); no
    # separate drop_index needed.
    op.drop_table("info_item_source_revisions", schema="information")


def downgrade() -> None:
    """Recreate the info_item_source_revisions pin table (empty)."""
    op.create_table(
        "info_item_source_revisions",
        sa.Column("info_item_id", sa.String(length=26), nullable=False),
        sa.Column("source_revision_id", sa.String(length=26), nullable=False),
        sa.Column("bound_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["info_item_id"],
            ["information.info_items.info_item_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_revision_id"],
            ["information.source_revisions.source_revision_id"],
        ),
        sa.PrimaryKeyConstraint("info_item_id", "source_revision_id"),
        schema="information",
    )
    op.create_index(
        "ix_iisr_item_bound_desc",
        "info_item_source_revisions",
        ["info_item_id", "bound_at"],
        unique=False,
        schema="information",
    )
