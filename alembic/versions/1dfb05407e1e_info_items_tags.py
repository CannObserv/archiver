"""info_items: tags

Revision ID: 1dfb05407e1e
Revises: 3f57fd148898
Create Date: 2026-11-09 21:00:00.000000

archiver#362 (epic #359 A6): tags on InfoItem, replacing Watcher's
``default_tags``. **D1:** ``text[] NOT NULL DEFAULT '{}'``, stored
de-duplicated and sorted by ``src.core.services.info_item_tags``; the empty
array is the one way to say "no tags". Every existing row takes ``'{}'``, and
nothing announces: tags never go on the bus.

**Expand-only** (archiver#330 D3): the previous release's ORM never names the
column, and the server default takes its inserts.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "1dfb05407e1e"
down_revision: str | Sequence[str] | None = "3f57fd148898"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMA = "information"


def upgrade() -> None:
    """Add the column; every existing row reads ``'{}'``."""
    op.add_column(
        "info_items",
        sa.Column(
            "tags",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        schema=_SCHEMA,
    )


def downgrade() -> None:
    """Drop it; every tag written since the upgrade is lost."""
    op.drop_column("info_items", "tags", schema=_SCHEMA)
