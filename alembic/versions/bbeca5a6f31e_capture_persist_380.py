"""persist_commands takes a capture occasion; capture_commands.persisted_at

Revision ID: bbeca5a6f31e
Revises: b10b1ce04a49
Create Date: 2026-11-11 16:00:00.000000

archiver#380 slice B: keep a viewport capture past ``blob_expires_at`` with a
``content.persist`` (Replicator's capture contract, C3).

- ``persist_commands.source_revision_id`` becomes nullable, beside a new
  ``capture_command_id`` (FK ``capture_commands``, ``CASCADE``). The CHECK
  ``ck_persist_commands_one_occasion`` requires exactly one. Every existing row
  carries a revision, so the CHECK validates as it is added.
- ``capture_commands.persisted_at``: the minimum ``blob_persisted`` time for the
  capture's digest, ``source_revisions.persisted_at``'s rule. NULL, no backfill.
- ``ix_capture_commands_fingerprint``, for the stamp.

**Expand-only** (archiver#330 D3): the previous release's ORM always writes
``source_revision_id`` and never names the new columns, so it passes the CHECK.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "bbeca5a6f31e"
down_revision: str | Sequence[str] | None = "b10b1ce04a49"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Relax the revision link, add the capture link and its CHECK, then persisted_at."""
    op.alter_column(
        "persist_commands",
        "source_revision_id",
        existing_type=sa.String(length=26),
        nullable=True,
        schema="information",
    )
    op.add_column(
        "persist_commands",
        sa.Column("capture_command_id", sa.Text(), nullable=True),
        schema="information",
    )
    op.create_foreign_key(
        "persist_commands_capture_command_id_fkey",
        "persist_commands",
        "capture_commands",
        ["capture_command_id"],
        ["command_id"],
        source_schema="information",
        referent_schema="information",
        ondelete="CASCADE",
    )
    op.create_check_constraint(
        "ck_persist_commands_one_occasion",
        "persist_commands",
        "num_nonnulls(source_revision_id, capture_command_id) = 1",
        schema="information",
    )
    op.create_index(
        "ix_persist_commands_capture",
        "persist_commands",
        ["capture_command_id"],
        unique=False,
        schema="information",
    )
    op.add_column(
        "capture_commands",
        sa.Column("persisted_at", sa.DateTime(timezone=True), nullable=True),
        schema="information",
    )
    op.create_index(
        "ix_capture_commands_fingerprint",
        "capture_commands",
        ["content_fingerprint"],
        unique=False,
        schema="information",
    )


def downgrade() -> None:
    """Reverse. Refused while a capture-occasioned persist exists (NOT NULL again)."""
    op.drop_index(
        "ix_capture_commands_fingerprint", table_name="capture_commands", schema="information"
    )
    op.drop_column("capture_commands", "persisted_at", schema="information")
    op.drop_index(
        "ix_persist_commands_capture", table_name="persist_commands", schema="information"
    )
    op.drop_constraint(
        "ck_persist_commands_one_occasion",
        "persist_commands",
        type_="check",
        schema="information",
    )
    op.drop_constraint(
        "persist_commands_capture_command_id_fkey",
        "persist_commands",
        type_="foreignkey",
        schema="information",
    )
    op.drop_column("persist_commands", "capture_command_id", schema="information")
    op.alter_column(
        "persist_commands",
        "source_revision_id",
        existing_type=sa.String(length=26),
        nullable=False,
        schema="information",
    )
