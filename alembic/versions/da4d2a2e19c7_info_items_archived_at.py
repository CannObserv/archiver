"""info_items: archived_at

Revision ID: da4d2a2e19c7
Revises: 44b797877fdb
Create Date: 2026-10-27 18:30:00.000000

archiver#361: the watch lifecycle's archived state, orthogonal to
``watch_active`` (D1). ``NULL`` on every existing row: nothing is archived, so
no item's announced ``active`` moves and the deploy emits nothing.

**Expand-only** (archiver#330 D3): the previous release's ORM never names the
column, and a nullable column with no default takes its inserts.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "da4d2a2e19c7"
down_revision: str | Sequence[str] | None = "44b797877fdb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMA = "information"


def upgrade() -> None:
    """Add the nullable column."""
    op.add_column(
        "info_items",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        schema=_SCHEMA,
    )


def downgrade() -> None:
    """Drop it; an archive made since the upgrade is lost, and the item resumes."""
    op.drop_column("info_items", "archived_at", schema=_SCHEMA)
