"""notification_subscriptions

Revision ID: c4d81f6a2e07
Revises: b7e3c95a1f20
Create Date: 2026-10-28 20:00:00.000000

archiver#363: notification subscriptions, replacing Watcher's
``notification_templates`` (design D3, D5; the coordinator brief's D1). A
CHECK ties ``scope`` to exactly its ref; the Domain ref is ``RESTRICT`` so a
Domain delete refuses while a subscription names it; the item ref cascades.
``imported_watcher_id`` is the importer's key (D6).

Empty on creation, and nothing publishes subscriptions: the deploy emits
nothing on any stream.

**Expand-only** (archiver#330 D3): a new table the previous release's ORM never
names.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c4d81f6a2e07"
down_revision: str | Sequence[str] | None = "b7e3c95a1f20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMA = "information"
_TABLE = "notification_subscriptions"


def upgrade() -> None:
    """Create the table and its two ref indexes."""
    op.create_table(
        _TABLE,
        sa.Column("id", sa.String(length=26), nullable=False),
        sa.Column("title", sa.String(length=100), nullable=False),
        sa.Column("scope", sa.String(length=10), nullable=False),
        sa.Column("domain_id", sa.String(length=26), nullable=True),
        sa.Column("info_item_id", sa.String(length=26), nullable=True),
        sa.Column("events", postgresql.ARRAY(sa.String(length=32)), nullable=False),
        sa.Column("content_config", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("remote_channel_id", sa.String(length=26), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("imported_watcher_id", sa.String(length=26), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "(scope = 'global' AND domain_id IS NULL AND info_item_id IS NULL)"
            " OR (scope = 'domain' AND domain_id IS NOT NULL AND info_item_id IS NULL)"
            " OR (scope = 'item' AND info_item_id IS NOT NULL AND domain_id IS NULL)",
            name="ck_notification_subscriptions_scope",
        ),
        sa.CheckConstraint(
            "cardinality(events) > 0 AND events <@ "
            "ARRAY['change_detected', 'watch_error', 'watch_recovered']::varchar[]",
            name="ck_notification_subscriptions_events",
        ),
        sa.CheckConstraint(
            "remote_channel_id ~ '^[0-9A-HJKMNP-TV-Z]{26}$'",
            name="ck_notification_subscriptions_channel",
        ),
        sa.ForeignKeyConstraint(["domain_id"], [f"{_SCHEMA}.domains.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["info_item_id"], [f"{_SCHEMA}.info_items.info_item_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "imported_watcher_id", name="uq_notification_subscriptions_imported_watcher_id"
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_information_notification_subscriptions_domain_id"),
        _TABLE,
        ["domain_id"],
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_information_notification_subscriptions_info_item_id"),
        _TABLE,
        ["info_item_id"],
        schema=_SCHEMA,
    )


def downgrade() -> None:
    """Drop the table; every subscription is lost (nothing dispatches from it yet)."""
    op.drop_table(_TABLE, schema=_SCHEMA)
