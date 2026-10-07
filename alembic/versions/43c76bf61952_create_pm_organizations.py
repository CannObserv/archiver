"""create pm_organizations and info_items.pm_org_id

Revision ID: 43c76bf61952
Revises: 7c4e1f2a9b30
Create Date: 2026-10-06 22:45:00.000000

archiver#304 - the Power Map org link. ``pm_organizations`` is the local
snapshot of each linked org, written by the link and the follower (#305);
``info_items.pm_org_id`` points an item at one. Additive: every existing item
stays unlinked, so nothing renders differently until an operator links one.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "43c76bf61952"
down_revision: str | Sequence[str] | None = "7c4e1f2a9b30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the snapshot table, then the nullable FK and its index."""
    op.create_table(
        "pm_organizations",
        sa.Column("pm_org_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("acronym", sa.Text(), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("succeeded_by", sa.Text(), nullable=True),
        sa.Column("merged_into", sa.Text(), nullable=True),
        sa.Column("renamed_from", sa.Text(), nullable=True),
        sa.Column("renamed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("etag", sa.Text(), nullable=True),
        sa.Column("pm_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("missing_since", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("pm_org_id"),
        schema="information",
    )
    op.add_column(
        "info_items",
        sa.Column("pm_org_id", sa.Text(), nullable=True),
        schema="information",
    )
    op.create_foreign_key(
        "info_items_pm_org_id_fkey",
        "info_items",
        "pm_organizations",
        ["pm_org_id"],
        ["pm_org_id"],
        source_schema="information",
        referent_schema="information",
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_info_items_pm_org_id",
        "info_items",
        ["pm_org_id"],
        unique=False,
        schema="information",
    )


def downgrade() -> None:
    """Drop the link, then the snapshots. Every item's org link is lost."""
    op.drop_index("ix_info_items_pm_org_id", table_name="info_items", schema="information")
    op.drop_constraint(
        "info_items_pm_org_id_fkey", "info_items", schema="information", type_="foreignkey"
    )
    op.drop_column("info_items", "pm_org_id", schema="information")
    op.drop_table("pm_organizations", schema="information")
