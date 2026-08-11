"""add watch_spec + watch_active to info_items

Archiver takes ownership of scheduling policy (archiver#150). Cadence and
active/paused state lived on Watcher's ``watched_items`` and were round-tripped
over the SDK; they become registry columns.

**Two columns, not one.** ``watch_spec`` is cadence policy — a validated
document (``src/core/watch_spec_schema/``). ``watch_active`` is per-item pause
state, deliberately *not* a key inside that document: a policy document shared
across items by the future reusable-policy table could not carry per-item pause,
and co-core's ``RegistryAnnouncementState`` types ``active`` on the announcement
envelope beside ``revoked`` so the three-state distinction has a schema
guarantee rather than resting on an untyped dict key.

Both defaults say "nobody has expressed an opinion yet":

- ``watch_spec`` defaults to ``{"schema_version": 1}`` — **no interval**. A
  resolved cadence would fabricate one for every existing row and override the
  consumer's own default, which may be a per-domain ``default_schedule_config``
  rather than a global constant.
- ``watch_active`` is ``NULL`` — *the registry has no opinion yet, keep doing
  what you are doing*. Defaulting it ``true`` would announce every paused item
  as unpaused the moment the producer lands, before the import has run.

Real values arrive from ``scripts/import_watch_specs.py``, which reads Watcher
over the SDK and is re-run immediately before the announcement producer
publishes.

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
            server_default=sa.text("'{\"schema_version\": 1}'::jsonb"),
        ),
        schema="information",
    )
    op.add_column(
        "info_items",
        sa.Column("watch_active", sa.Boolean(), nullable=True),
        schema="information",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("info_items", "watch_active", schema="information")
    op.drop_column("info_items", "watch_spec", schema="information")
