"""widen watch_status.health and applied_interval to TEXT

Revision ID: c81f4a2e7d36
Revises: a7c3e91d5b02
Create Date: 2026-08-14 09:10:00.000000

archiver#151 CR round 1, finding 1a. Both fields are unconstrained ``str`` on
the co-core contract, and ``health``'s vocabulary is documented as expected to
grow. A bounded column turns a longer-than-expected value into a write the
consumer can never complete — and with no DLQ and a cursor that only advances
on success, that stalled the whole stream silently.

varchar → text is a metadata-only change in PostgreSQL (no table rewrite, no
lock beyond ACCESS EXCLUSIVE for the catalog update), and widening cannot
truncate existing rows.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c81f4a2e7d36"
down_revision: str | Sequence[str] | None = "a7c3e91d5b02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column(
        "watch_status",
        "health",
        existing_type=sa.String(length=100),
        type_=sa.Text(),
        existing_nullable=True,
        schema="information",
    )
    op.alter_column(
        "watch_status",
        "applied_interval",
        existing_type=sa.String(length=20),
        type_=sa.Text(),
        existing_nullable=True,
        schema="information",
    )


def downgrade() -> None:
    """Downgrade schema.

    Narrowing can fail on rows that outgrew the old bound — which is the whole
    reason the column was widened. Deliberately not made lossy with a USING
    clause: an operator downgrading past this point should see the error rather
    than silently lose a reported value.
    """
    op.alter_column(
        "watch_status",
        "applied_interval",
        existing_type=sa.Text(),
        type_=sa.String(length=20),
        existing_nullable=True,
        schema="information",
    )
    op.alter_column(
        "watch_status",
        "health",
        existing_type=sa.Text(),
        type_=sa.String(length=100),
        existing_nullable=True,
        schema="information",
    )
