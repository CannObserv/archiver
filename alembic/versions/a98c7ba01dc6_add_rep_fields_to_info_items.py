"""add rep_fields to info_items

Revision ID: a98c7ba01dc6
Revises: d932fbc8d1cd
Create Date: 2026-05-08 18:54:18.437031

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a98c7ba01dc6"
down_revision: str | Sequence[str] | None = "d932fbc8d1cd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add rep_fields JSONB column to info_items."""
    op.add_column(
        "info_items",
        sa.Column(
            "rep_fields",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        schema="information",
    )


def downgrade() -> None:
    """Remove rep_fields column from info_items."""
    op.drop_column("info_items", "rep_fields", schema="information")
