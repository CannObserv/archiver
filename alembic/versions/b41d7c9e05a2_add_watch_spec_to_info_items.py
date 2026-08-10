"""add watch_spec to info_items

Archiver takes ownership of scheduling policy (archiver#150). Cadence and
active/paused state lived on Watcher's ``watched_items`` and were round-tripped
over the SDK; they become a validated document on the registry's own row.

Non-null with a server default of ``{"schema_version": 1, "active": true}``.
The default deliberately carries **no** ``interval``: a resolved cadence here
would fabricate one for every existing row and override the consumer's own
default, which may be a per-domain ``default_schedule_config`` rather than a
global constant. Absent means "consumer applies its default". The real values
arrive from the one-time import (``scripts/import_watch_specs.py``), which runs
against production before the announcement producer publishes.

Revision ID: b41d7c9e05a2
Revises: 3f2a17c4be90
Create Date: 2026-08-10 21:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b41d7c9e05a2"
down_revision: str | Sequence[str] | None = "3f2a17c4be90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "info_items",
        sa.Column(
            "watch_spec",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text('\'{"schema_version": 1, "active": true}\'::jsonb'),
        ),
        schema="information",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("info_items", "watch_spec", schema="information")
