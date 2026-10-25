"""domains: min_interval_seconds and default_watch_spec

Revision ID: 173c1af91def
Revises: 80ca1ae1a1ce
Create Date: 2026-10-24 20:00:00.000000

archiver#360: Archiver becomes the sole owner of per-host policy (design D4).
Both columns are **dark** - stored and editable, read by no producer until
#366 (``content.fetch-policy``, flip F1) and #364 (cadence resolution, F2).

``min_interval_seconds`` is NOT NULL with Watcher's default of 1.0, so the
three existing rows land on the value Watcher holds for them. The CHECK spells
"finite and >= 0" out in full: Postgres sorts ``NaN`` above every number, so
``>= 0`` alone admits it.

**Expand-only** (archiver#330 D3): the previous release's ORM inserts domains
without either column; the server default and the nullable cadence take them.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "173c1af91def"
down_revision: str | Sequence[str] | None = "80ca1ae1a1ce"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMA = "information"
_CHECK = "ck_domains_min_interval_seconds"


def upgrade() -> None:
    """Add the two columns and the finiteness check."""
    op.add_column(
        "domains",
        sa.Column("min_interval_seconds", sa.Float(), nullable=False, server_default="1.0"),
        schema=_SCHEMA,
    )
    op.add_column(
        "domains",
        sa.Column("default_watch_spec", postgresql.JSONB(), nullable=True),
        schema=_SCHEMA,
    )
    op.create_check_constraint(
        _CHECK,
        "domains",
        "min_interval_seconds >= 0 AND min_interval_seconds < 'Infinity'"
        " AND min_interval_seconds <> 'NaN'",
        schema=_SCHEMA,
    )


def downgrade() -> None:
    """Drop them; an edit made since the upgrade is lost."""
    op.drop_constraint(_CHECK, "domains", schema=_SCHEMA, type_="check")
    op.drop_column("domains", "default_watch_spec", schema=_SCHEMA)
    op.drop_column("domains", "min_interval_seconds", schema=_SCHEMA)
