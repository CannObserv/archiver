"""add spec comparison columns to source_revisions

The flag half of archiver#139's record-and-flag policy, unblocked by
cannobserv#309 (co-core >=0.8.1 owns the ``spec_fingerprint`` derivation, so the
registry can finally recompute its own specs' fingerprints and compare).

``spec_match`` carries the outcome (``current`` / ``superseded`` /
``incomparable``, NULL when the observation reported no fingerprint) and
``spec_position`` the ``source_specs`` index matched, set only for ``current``.

Both nullable and backfill-free: rows written before this — and every row the
HTTP authoring path writes, which never carries a ``spec_fingerprint`` — have
nothing to compare, and NULL says exactly that.

Revision ID: 3f2a17c4be90
Revises: 9486c8e6c9a7
Create Date: 2026-08-09 14:20:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3f2a17c4be90"
down_revision: str | Sequence[str] | None = "9486c8e6c9a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "source_revisions",
        sa.Column("spec_match", sa.Text(), nullable=True),
        schema="information",
    )
    op.add_column(
        "source_revisions",
        sa.Column("spec_position", sa.Integer(), nullable=True),
        schema="information",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("source_revisions", "spec_position", schema="information")
    op.drop_column("source_revisions", "spec_match", schema="information")
