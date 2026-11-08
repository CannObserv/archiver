"""watch_check_commands + watch_status C-c levels

Revision ID: 3f57fd148898
Revises: 01193055fc9c
Create Date: 2026-11-08 06:00:00.000000

archiver#370 (check-now via ``info.watch-check``, epic #359 A11).

- **D1:** ``watch_status`` gains the three ``WatchStatusState`` levels co-core
  added in C-c: ``last_full_fetch_at``, ``health_reason``,
  ``health_status_code``. All nullable, no backfill: existing rows fill on
  Watcher's next periodic republish.
- **D2:** ``watch_check_commands``, one row per check-now click, written with
  its outbox row. Cascades with the item; ``requested_by`` is ``SET NULL``.

Empty on creation, and nothing writes it while ``ARCHIVER_WATCH_CHECK_ENABLED``
is unset (F4). **Expand-only** (archiver#330 D3): new nullable columns and a
new table the previous release's ORM never names.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3f57fd148898"
down_revision: str | Sequence[str] | None = "01193055fc9c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the three levels, then the command table and its index."""
    op.add_column(
        "watch_status",
        sa.Column("last_full_fetch_at", sa.DateTime(timezone=True), nullable=True),
        schema="information",
    )
    op.add_column(
        "watch_status", sa.Column("health_reason", sa.Text(), nullable=True), schema="information"
    )
    op.add_column(
        "watch_status",
        sa.Column("health_status_code", sa.Integer(), nullable=True),
        schema="information",
    )
    op.create_table(
        "watch_check_commands",
        sa.Column("command_id", sa.Text(), nullable=False),
        sa.Column("info_item_id", sa.String(length=26), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("requested_by", sa.String(length=26), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("rejected_reason", sa.Text(), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["info_item_id"], ["information.info_items.info_item_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["requested_by"], ["information.app_users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("command_id"),
        schema="information",
    )
    op.create_index(
        "ix_watch_check_commands_item_requested",
        "watch_check_commands",
        ["info_item_id", "requested_at"],
        unique=False,
        schema="information",
    )


def downgrade() -> None:
    """Drop the table and the three columns: the command history is lost."""
    op.drop_index(
        "ix_watch_check_commands_item_requested",
        table_name="watch_check_commands",
        schema="information",
    )
    op.drop_table("watch_check_commands", schema="information")
    op.drop_column("watch_status", "health_status_code", schema="information")
    op.drop_column("watch_status", "health_reason", schema="information")
    op.drop_column("watch_status", "last_full_fetch_at", schema="information")
