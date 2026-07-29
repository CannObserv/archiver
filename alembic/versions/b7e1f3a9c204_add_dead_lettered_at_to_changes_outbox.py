"""add dead_lettered_at to changes_outbox

Terminal state for deterministically-unpublishable (poison) outbox rows so the
publisher stops retrying them forever (archiver#107). Also narrows the
unpublished partial index to exclude dead-lettered rows, matching the drain
loop's predicate.

Revision ID: b7e1f3a9c204
Revises: 4413805453dd
Create Date: 2026-07-29 19:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7e1f3a9c204"
down_revision: str | Sequence[str] | None = "4413805453dd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "changes_outbox",
        sa.Column("dead_lettered_at", sa.DateTime(timezone=True), nullable=True),
        schema="information",
    )
    # Re-point the unpublished partial index at the drain loop's exact predicate:
    # candidates are rows with both published_at AND dead_lettered_at NULL.
    op.drop_index(
        "ix_changes_outbox_unpublished_created",
        table_name="changes_outbox",
        schema="information",
        postgresql_where=sa.text("published_at IS NULL"),
    )
    op.create_index(
        "ix_changes_outbox_unpublished_created",
        "changes_outbox",
        ["created_at"],
        unique=False,
        schema="information",
        postgresql_where=sa.text("published_at IS NULL AND dead_lettered_at IS NULL"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_changes_outbox_unpublished_created",
        table_name="changes_outbox",
        schema="information",
        postgresql_where=sa.text("published_at IS NULL AND dead_lettered_at IS NULL"),
    )
    op.create_index(
        "ix_changes_outbox_unpublished_created",
        "changes_outbox",
        ["created_at"],
        unique=False,
        schema="information",
        postgresql_where=sa.text("published_at IS NULL"),
    )
    op.drop_column("changes_outbox", "dead_lettered_at", schema="information")
