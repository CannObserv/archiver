"""create info_item_rep_specs

Revision ID: 0ba89c365552
Revises: 5a08d8e2fc5e
Create Date: 2026-05-08 19:47:31.976508

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0ba89c365552"
down_revision: str | Sequence[str] | None = "5a08d8e2fc5e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create info_item_rep_specs table with effective-dated assignments."""
    op.create_table(
        "info_item_rep_specs",
        sa.Column("id", sa.String(length=26), nullable=False),
        sa.Column("info_item_id", sa.String(length=26), nullable=False),
        sa.Column("rep_spec_id", sa.String(length=26), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("public_url", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["info_item_id"],
            ["information.info_items.info_item_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["rep_spec_id"], ["information.rep_specs.rep_spec_id"]),
        sa.PrimaryKeyConstraint("id"),
        schema="information",
    )
    op.create_index(
        "ix_iirs_item_active",
        "info_item_rep_specs",
        ["info_item_id"],
        unique=False,
        schema="information",
        postgresql_where=sa.text("deactivated_at IS NULL"),
    )
    op.create_index(
        "ix_iirs_rep_spec",
        "info_item_rep_specs",
        ["rep_spec_id"],
        unique=False,
        schema="information",
    )


def downgrade() -> None:
    """Drop info_item_rep_specs table."""
    op.drop_index(
        "ix_iirs_rep_spec",
        table_name="info_item_rep_specs",
        schema="information",
    )
    op.drop_index(
        "ix_iirs_item_active",
        table_name="info_item_rep_specs",
        schema="information",
        postgresql_where=sa.text("deactivated_at IS NULL"),
    )
    op.drop_table("info_item_rep_specs", schema="information")
