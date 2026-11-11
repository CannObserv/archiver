"""info_sources.capture_policy; capture_commands' revision link, re-issue chain, attempt

Revision ID: c4a9e1f07d2b
Revises: bbeca5a6f31e
Create Date: 2026-11-11 17:00:00.000000

archiver#380 slice C: a per-source capture policy (D2), a capture on each new
revision for sources that opt in (D3), and the reaper's capped re-issue of a
silent capture (Replicator's capture contract, C2).

- ``info_sources.capture_policy`` JSONB, NULL = no policy (the default profile
  on demand, no revision captures). Validated on write
  (``src.core.capture_policy``) and by the stored-document sweep.
- ``capture_commands.source_revision_id`` (FK ``source_revisions``, SET NULL):
  the revision a capture accompanies. Temporal: the capture renders the live page.
- ``capture_commands.reissue_of`` (self FK, SET NULL) and ``attempt`` (NOT NULL,
  server default 1, CHECK >= 1): the re-issue chain and its cap.

**Expand-only** (archiver#330 D3): every column is nullable or server-defaulted,
so the previous release's ORM, which names none of them, still writes.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c4a9e1f07d2b"
down_revision: str | Sequence[str] | None = "bbeca5a6f31e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the policy, then the three capture_commands columns, their FKs, CHECK and index."""
    op.add_column(
        "info_sources",
        sa.Column("capture_policy", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        schema="information",
    )
    op.add_column(
        "capture_commands",
        sa.Column("source_revision_id", sa.String(length=26), nullable=True),
        schema="information",
    )
    op.add_column(
        "capture_commands",
        sa.Column("reissue_of", sa.Text(), nullable=True),
        schema="information",
    )
    op.add_column(
        "capture_commands",
        sa.Column("attempt", sa.SmallInteger(), server_default=sa.text("1"), nullable=False),
        schema="information",
    )
    op.create_foreign_key(
        "capture_commands_source_revision_id_fkey",
        "capture_commands",
        "source_revisions",
        ["source_revision_id"],
        ["source_revision_id"],
        source_schema="information",
        referent_schema="information",
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "capture_commands_reissue_of_fkey",
        "capture_commands",
        "capture_commands",
        ["reissue_of"],
        ["command_id"],
        source_schema="information",
        referent_schema="information",
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_capture_commands_attempt",
        "capture_commands",
        "attempt >= 1",
        schema="information",
    )
    op.create_index(
        "ix_capture_commands_revision",
        "capture_commands",
        ["source_revision_id"],
        unique=False,
        schema="information",
    )


def downgrade() -> None:
    """Reverse. Drops the policies and the re-issue history with their columns."""
    op.drop_index(
        "ix_capture_commands_revision", table_name="capture_commands", schema="information"
    )
    op.drop_constraint(
        "ck_capture_commands_attempt", "capture_commands", type_="check", schema="information"
    )
    op.drop_constraint(
        "capture_commands_reissue_of_fkey",
        "capture_commands",
        type_="foreignkey",
        schema="information",
    )
    op.drop_constraint(
        "capture_commands_source_revision_id_fkey",
        "capture_commands",
        type_="foreignkey",
        schema="information",
    )
    op.drop_column("capture_commands", "attempt", schema="information")
    op.drop_column("capture_commands", "reissue_of", schema="information")
    op.drop_column("capture_commands", "source_revision_id", schema="information")
    op.drop_column("info_sources", "capture_policy", schema="information")
