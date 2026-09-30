"""info_items.announced_revoked: the kind of the last delta announcement

Revision ID: b7e2d94c1a38
Revises: 70f32f641751
Create Date: 2026-09-30 22:00:00.000000

archiver#293 - the binding path re-tombstoned an already-revoked item.

``_announce`` tombstoned whenever an item was unannounceable and
``announcement_generation > 0``; it could not tell "was live, now isn't" (a
tombstone is owed) from "was already revoked" (nothing changed). Binding a
spec-less source to a revoked item, or re-saving empty ``source_specs`` on a
source backing several, burned a generation and an outbox row per item per
mutation. The column records the kind of the last announcement, written in the
same UPDATE as the bump, so the skip can key on it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7e2d94c1a38"
down_revision: str | Sequence[str] | None = "70f32f641751"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the column; every row starts ``false``."""
    op.add_column(
        "info_items",
        sa.Column("announced_revoked", sa.Boolean(), server_default="false", nullable=False),
        schema="information",
    )


def downgrade() -> None:
    """Drop the column."""
    op.drop_column("info_items", "announced_revoked", schema="information")
