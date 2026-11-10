"""capture_commands

Revision ID: b10b1ce04a49
Revises: 1dfb05407e1e
Create Date: 2026-11-10 23:00:00.000000

archiver#380 slice A: one row per ``content.capture`` command, written with its
outbox row, closed by ``capture_stored`` / ``capture_failed`` on
``content.artifacts`` or abandoned by the reaper. Cascades with the source;
``requested_by`` is ``SET NULL``.

Empty on creation, and nothing writes it while ``ARCHIVER_CAPTURE_ENABLED`` is
unset. **Expand-only** (archiver#330 D3): a new table the previous release's ORM
never names.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b10b1ce04a49"
down_revision: str | Sequence[str] | None = "1dfb05407e1e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the command table and its two indexes."""
    op.create_table(
        "capture_commands",
        sa.Column("command_id", sa.Text(), nullable=False),
        sa.Column("info_source_id", sa.String(length=26), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("viewport_width", sa.Integer(), nullable=False),
        sa.Column("viewport_height", sa.Integer(), nullable=False),
        sa.Column("full_page", sa.Boolean(), nullable=False),
        sa.Column("wait", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("requested_by", sa.String(length=26), nullable=True),
        sa.Column(
            "issued_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("terminal", sa.Boolean(), nullable=True),
        sa.Column("content_fingerprint", sa.Text(), nullable=True),
        sa.Column("blob_uri", sa.Text(), nullable=True),
        sa.Column("media_type", sa.Text(), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("image_width", sa.Integer(), nullable=True),
        sa.Column("image_height", sa.Integer(), nullable=True),
        sa.Column("final_url", sa.Text(), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("blob_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_fact_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "state IN ('requested', 'stored', 'failed', 'abandoned')",
            name="ck_capture_commands_state",
        ),
        sa.ForeignKeyConstraint(
            ["info_source_id"], ["information.info_sources.info_source_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["requested_by"], ["information.app_users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("command_id"),
        schema="information",
    )
    op.create_index(
        "ix_capture_commands_open",
        "capture_commands",
        ["issued_at"],
        unique=False,
        schema="information",
        postgresql_where=sa.text("closed_at IS NULL AND state = 'requested'"),
    )
    op.create_index(
        "ix_capture_commands_source_issued",
        "capture_commands",
        ["info_source_id", "issued_at"],
        unique=False,
        schema="information",
    )


def downgrade() -> None:
    """Drop the table: the capture history is lost."""
    op.drop_index(
        "ix_capture_commands_source_issued", table_name="capture_commands", schema="information"
    )
    op.drop_index("ix_capture_commands_open", table_name="capture_commands", schema="information")
    op.drop_table("capture_commands", schema="information")
