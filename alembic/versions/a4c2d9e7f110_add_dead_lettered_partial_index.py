"""add partial index on changes_outbox.dead_lettered_at

Backs the dead_lettered_count observability query (archiver#112). The table
has no pruner, so a bare COUNT(*) WHERE dead_lettered_at IS NOT NULL degrades
to an ever-slower seq scan; the partial index stays tiny (poison rows only).

Revision ID: a4c2d9e7f110
Revises: 1bbd3b3722e3
Create Date: 2026-08-27 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a4c2d9e7f110"
down_revision: str | Sequence[str] | None = "1bbd3b3722e3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index(
        "ix_changes_outbox_dead_lettered",
        "changes_outbox",
        ["dead_lettered_at"],
        unique=False,
        schema="information",
        postgresql_where=sa.text("dead_lettered_at IS NOT NULL"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_changes_outbox_dead_lettered",
        table_name="changes_outbox",
        schema="information",
        postgresql_where=sa.text("dead_lettered_at IS NOT NULL"),
    )
