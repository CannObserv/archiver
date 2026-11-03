"""notification_dispatches

Revision ID: 01193055fc9c
Revises: c4d81f6a2e07
Create Date: 2026-11-02 20:32:30.277273

archiver#369 (D1): one row per (``info.watch-events`` fact, matching
subscription), plus one per error reminder. Both the shadow log and the
dispatch outbox: ``mode`` says which. Unique on (``event_id``,
``subscription_id``, ``reminder``) so a redelivered fact is a no-op, and on
``idempotency_key``, Notifier's key. The subscription ref is ``SET NULL``, so a
delete keeps the history and its pending rows end ``skipped``.

Empty on creation. Nothing publishes from it: the deploy emits nothing on any
stream, and ``changes_outbox`` is untouched.

**Expand-only** (archiver#330 D3): a new table the previous release's ORM never
names.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "01193055fc9c"
down_revision: str | Sequence[str] | None = "c4d81f6a2e07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the table and its four indexes."""
    op.create_table(
        "notification_dispatches",
        sa.Column("id", sa.String(length=26), nullable=False),
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("reminder", sa.Integer(), server_default="0", nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("subscription_id", sa.String(length=26), nullable=True),
        sa.Column("info_item_id", sa.String(length=26), nullable=False),
        sa.Column("remote_channel_id", sa.String(length=26), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reminded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fact", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("mode", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("notifier_dispatch_id", sa.String(length=26), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "(mode = 'shadow') = (status = 'shadow')", name="ck_notification_dispatches_shadow"
        ),
        sa.CheckConstraint(
            "event_type IN ('change_detected', 'watch_error', 'watch_recovered')",
            name="ck_notification_dispatches_event_type",
        ),
        sa.CheckConstraint("mode IN ('shadow', 'send')", name="ck_notification_dispatches_mode"),
        sa.CheckConstraint(
            "reminder >= 0 AND (reminder = 0 OR event_type = 'watch_error')"
            " AND (reminder = 0) = (reminded_at IS NULL)",
            name="ck_notification_dispatches_reminder",
        ),
        sa.CheckConstraint(
            "status IN ('shadow', 'pending', 'sent', 'failed', 'skipped')",
            name="ck_notification_dispatches_status",
        ),
        sa.ForeignKeyConstraint(
            ["subscription_id"], ["information.notification_subscriptions.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "event_id",
            "subscription_id",
            "reminder",
            name="uq_notification_dispatches_event_subscription_reminder",
        ),
        sa.UniqueConstraint("idempotency_key", name="uq_notification_dispatches_idempotency_key"),
        schema="information",
    )
    op.create_index(
        op.f("ix_information_notification_dispatches_subscription_id"),
        "notification_dispatches",
        ["subscription_id"],
        unique=False,
        schema="information",
    )
    op.create_index(
        "ix_notification_dispatches_created_at",
        "notification_dispatches",
        ["created_at"],
        unique=False,
        schema="information",
    )
    op.create_index(
        "ix_notification_dispatches_item_occurred",
        "notification_dispatches",
        ["info_item_id", "occurred_at"],
        unique=False,
        schema="information",
    )
    op.create_index(
        "ix_notification_dispatches_pending",
        "notification_dispatches",
        ["id"],
        unique=False,
        schema="information",
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    """Drop the table: the shadow log and any unsent row are lost."""
    op.drop_index(
        "ix_notification_dispatches_pending",
        table_name="notification_dispatches",
        schema="information",
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.drop_index(
        "ix_notification_dispatches_item_occurred",
        table_name="notification_dispatches",
        schema="information",
    )
    op.drop_index(
        "ix_notification_dispatches_created_at",
        table_name="notification_dispatches",
        schema="information",
    )
    op.drop_index(
        op.f("ix_information_notification_dispatches_subscription_id"),
        table_name="notification_dispatches",
        schema="information",
    )
    op.drop_table("notification_dispatches", schema="information")
