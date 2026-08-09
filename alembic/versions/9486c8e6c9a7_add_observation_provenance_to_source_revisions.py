"""add observation provenance columns to source_revisions

Three fields that arrive on ``SourceRevisionObservedEvent`` (cannobserv#301) and
had nowhere to land: ``source_media_type`` (what the origin served, as against
the existing ``content_media_type``, which describes the extracted text),
``spec_fingerprint`` (which ``source_specs`` the producer extracted under), and
``command_id`` (correlation back to the fetch). archiver#139.

All nullable and backfill-free: rows written through the HTTP authoring/backfill
path supply none of them, and two of the three are optional on the wire.

Revision ID: 9486c8e6c9a7
Revises: b7e1f3a9c204
Create Date: 2026-08-09 05:03:14.243751

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9486c8e6c9a7"
down_revision: str | Sequence[str] | None = "b7e1f3a9c204"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "source_revisions",
        sa.Column("source_media_type", sa.Text(), nullable=True),
        schema="information",
    )
    op.add_column(
        "source_revisions",
        sa.Column("spec_fingerprint", sa.Text(), nullable=True),
        schema="information",
    )
    op.add_column(
        "source_revisions",
        sa.Column("command_id", sa.Text(), nullable=True),
        schema="information",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("source_revisions", "command_id", schema="information")
    op.drop_column("source_revisions", "spec_fingerprint", schema="information")
    op.drop_column("source_revisions", "source_media_type", schema="information")
