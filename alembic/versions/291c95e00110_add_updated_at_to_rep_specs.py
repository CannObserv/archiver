"""add updated_at to rep_specs

Audit column for the tiered RepSpec mutability contract (archiver#83). See
docs/plans/2026-07-20-83-rep-spec-document-editing-adr.md.

Nullable with no default and no backfill: NULL means "never edited". Backfilling
existing rows with ``created_at`` would assert an edit that never happened, and
the whole point of the column is to distinguish those two states.

Revision ID: 291c95e00110
Revises: fa99ef9f1dbd
Create Date: 2026-07-20 03:52:15.575104

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "291c95e00110"
down_revision: str | Sequence[str] | None = "fa99ef9f1dbd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the nullable rep_specs.updated_at audit column."""
    op.add_column(
        "rep_specs",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        schema="information",
    )


def downgrade() -> None:
    """Drop rep_specs.updated_at, discarding edit timestamps."""
    op.drop_column("rep_specs", "updated_at", schema="information")
