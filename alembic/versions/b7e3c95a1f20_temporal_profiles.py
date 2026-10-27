"""temporal_profiles

Revision ID: b7e3c95a1f20
Revises: da4d2a2e19c7
Create Date: 2026-10-27 23:00:00.000000

archiver#365: Watcher's temporal profiles, ported (design D5, D7). One per
InfoItem, keyed by its id. ``resolved_interval`` and ``evaluated_on`` persist
the profile's current result, so the announce path never reads the clock (the
coordinator brief's D1); ``fired_at`` makes the post-action one-shot (D4).

Empty on creation: production holds 0 profiles in Watcher and none here, so no
item's announced interval moves and the deploy emits nothing.

**Expand-only** (archiver#330 D3): a new table the previous release's ORM never
names.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b7e3c95a1f20"
down_revision: str | Sequence[str] | None = "da4d2a2e19c7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMA = "information"


def upgrade() -> None:
    """Create the table."""
    op.create_table(
        "temporal_profiles",
        sa.Column("info_item_id", sa.String(length=26), nullable=False),
        sa.Column("profile_type", sa.String(length=20), nullable=False),
        sa.Column("reference_date", sa.Date(), nullable=True),
        sa.Column("date_range_start", sa.Date(), nullable=True),
        sa.Column("date_range_end", sa.Date(), nullable=True),
        sa.Column(
            "rules",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("post_action", sa.String(length=20), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("resolved_interval", sa.String(length=32), nullable=True),
        sa.Column("evaluated_on", sa.Date(), nullable=False),
        sa.Column("fired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "profile_type IN ('event', 'seasonal', 'deadline')",
            name="ck_temporal_profiles_type",
        ),
        sa.CheckConstraint(
            "post_action IN ('reduce_frequency', 'deactivate', 'archive')",
            name="ck_temporal_profiles_post_action",
        ),
        sa.CheckConstraint(
            "(profile_type IN ('event', 'deadline') AND reference_date IS NOT NULL"
            " AND date_range_start IS NULL AND date_range_end IS NULL)"
            " OR (profile_type = 'seasonal' AND reference_date IS NULL"
            " AND date_range_start IS NOT NULL AND date_range_end IS NOT NULL"
            " AND date_range_start <= date_range_end)",
            name="ck_temporal_profiles_dates",
        ),
        sa.CheckConstraint("jsonb_typeof(rules) = 'array'", name="ck_temporal_profiles_rules"),
        sa.ForeignKeyConstraint(
            ["info_item_id"],
            [f"{_SCHEMA}.info_items.info_item_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("info_item_id"),
        schema=_SCHEMA,
    )


def downgrade() -> None:
    """Drop the table; every profile is lost, and its items announce their own cadence."""
    op.drop_table("temporal_profiles", schema=_SCHEMA)
