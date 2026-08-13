"""watch_status cache, bus_tail_cursors, last_observed_at, announced_at

Revision ID: a7c3e91d5b02
Revises: f5c522f65657
Create Date: 2026-08-13 18:40:00.000000

archiver#151 — consume ``info.watch-status``:

- ``watch_status``: local LWW cache of Watcher's reported scheduler state,
  one row per InfoItem; the watched-item panel renders from it with zero SDK
  calls. Revoked slots are deleted, not marked.
- ``bus_tail_cursors``: resume point per tailed stream so a restart is a
  delta from the last-seen id, not a full 0-0 replay.
- ``info_sources.last_observed_at``: durable provenance — "verified current
  as of T". Reported by Watcher, a lower bound (publish coalescing), written
  monotonically by the consumer only.
- ``info_items.announced_at``: when announcement_generation last bumped,
  stamped in the same atomic UPDATE — the drift detector's clock, since
  changes_outbox.published_at is prunable under the #141 retention split.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7c3e91d5b02"
down_revision: str | Sequence[str] | None = "f5c522f65657"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "watch_status",
        sa.Column("info_item_id", sa.String(length=26), nullable=False),
        sa.Column("applied_generation", sa.BigInteger(), nullable=False),
        sa.Column("applied_active", sa.Boolean(), nullable=True),
        sa.Column("applied_interval", sa.String(length=20), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("health", sa.String(length=100), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["info_item_id"],
            ["information.info_items.info_item_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("info_item_id"),
        schema="information",
    )
    op.create_table(
        "bus_tail_cursors",
        sa.Column("stream", sa.String(length=100), nullable=False),
        sa.Column("last_id", sa.String(length=50), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("stream"),
        schema="information",
    )
    op.add_column(
        "info_sources",
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=True),
        schema="information",
    )
    op.add_column(
        "info_items",
        sa.Column("announced_at", sa.DateTime(timezone=True), nullable=True),
        schema="information",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("info_items", "announced_at", schema="information")
    op.drop_column("info_sources", "last_observed_at", schema="information")
    op.drop_table("bus_tail_cursors", schema="information")
    op.drop_table("watch_status", schema="information")
