"""add watcher_item_id to info_items

Revision ID: fff827419c6c
Revises: c3d4e5f6a7b8
Create Date: 2026-06-10 21:11:54.340174

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "fff827419c6c"
down_revision: str | Sequence[str] | None = "c3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Primary change: store Watcher WatchedItem ID for control-plane integration
    op.add_column(
        "info_items",
        sa.Column("watcher_item_id", sa.String(length=50), nullable=True),
        schema="information",
    )
    # Cleanup: domain_name FK and index on info_sources were removed from the ORM
    # in #48 (info_source simplification) but the DB constraints were not dropped at
    # the time. Drop them now to align DB with the model.
    op.drop_index("ix_info_sources_domain_name", table_name="info_sources", schema="information")
    op.drop_constraint(
        "fk_info_sources_domain_name", "info_sources", schema="information", type_="foreignkey"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("info_items", "watcher_item_id", schema="information")
    op.create_foreign_key(
        "fk_info_sources_domain_name",
        "info_sources",
        "domains",
        ["domain_name"],
        ["name"],
        source_schema="information",
        referent_schema="information",
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_info_sources_domain_name",
        "info_sources",
        ["domain_name"],
        unique=False,
        schema="information",
    )
