"""index published changes_outbox rows for the retention pass

Partial index over ``published_at IS NOT NULL`` backing the archiver#189
retention pass. The two pre-existing partial indexes on this table both exclude
published rows (one is the drain's live queue, one is the dead-letter set), so
without this the prune's ``published_at < cutoff`` select degrades to a seq scan
of exactly the rows it exists to bound.

Plain (non-concurrent) CREATE INDEX: the table holds tens of rows at the time
this lands, so the brief ACCESS EXCLUSIVE lock is not worth an autocommit-block
migration. Building the index while the table is still small is half the point
of shipping the pruner now rather than when it hurts.

Revision ID: c9f4a1b7d503
Revises: a4c2d9e7f110
Create Date: 2026-08-29 18:20:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c9f4a1b7d503"
down_revision: str | Sequence[str] | None = "a4c2d9e7f110"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index(
        "ix_changes_outbox_published",
        "changes_outbox",
        ["published_at"],
        unique=False,
        schema="information",
        postgresql_where=sa.text("published_at IS NOT NULL"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_changes_outbox_published",
        table_name="changes_outbox",
        schema="information",
        postgresql_where=sa.text("published_at IS NOT NULL"),
    )
