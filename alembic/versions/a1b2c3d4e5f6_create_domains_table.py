"""create_domains_table

Revision ID: a1b2c3d4e5f6
Revises: c9d8e7f6a5b4
Create Date: 2026-06-04 00:00:00.000000

Minimal domain registry — hostname + lifecycle state + operator notes.
Rate-limiter columns intentionally absent (Watcher-owned).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "c9d8e7f6a5b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "domains",
        sa.Column("id", sa.String(26), nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_domains"),
        sa.UniqueConstraint("name", name="uq_domains_name"),
        schema="information",
    )


def downgrade() -> None:
    op.drop_table("domains", schema="information")
