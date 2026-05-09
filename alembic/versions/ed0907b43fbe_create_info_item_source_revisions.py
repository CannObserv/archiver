"""create info_item_source_revisions

Revision ID: ed0907b43fbe
Revises: d86c8caac3d4
Create Date: 2026-05-08 19:29:17.137927

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ed0907b43fbe"
down_revision: str | Sequence[str] | None = "d86c8caac3d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
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


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_iisr_item_bound_desc",
        table_name="info_item_source_revisions",
        schema="information",
    )
    op.drop_table("info_item_source_revisions", schema="information")
