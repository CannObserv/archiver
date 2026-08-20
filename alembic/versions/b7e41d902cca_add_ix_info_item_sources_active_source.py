"""add ix_info_item_sources_active_source

Domain detail (#176) lists the InfoItems bound to a domain's InfoSources, which
enters ``info_item_sources`` by ``info_source_id`` — the first read path to do
so. Every earlier consumer entered by ``info_item_id``, which the composite
primary key leads with; Postgres has no skip scan, so a lookup by the second PK
column alone cannot use that index and falls back to a sequential scan. The
domain screen runs the traversal twice per render (heading COUNT + page), so
the scan is paid on every view.

Partial on ``deactivated_at IS NULL`` because that predicate is in the query: a
deactivated binding is a superseded primary, succession history rather than a
current dependency on the domain.

The table is small enough that a plain CREATE INDEX is fine. If it grows large
first, switch to ``postgresql_concurrently=True`` (which additionally requires
the migration to run outside a transaction).

Revision ID: b7e41d902cca
Revises: 39f21d31fdec
Create Date: 2026-08-19 21:26:11.402118

"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "b7e41d902cca"
down_revision: str | Sequence[str] | None = "39f21d31fdec"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index(
        "ix_info_item_sources_active_source",
        "info_item_sources",
        ["info_source_id"],
        unique=False,
        schema="information",
        postgresql_where=text("deactivated_at IS NULL"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_info_item_sources_active_source",
        table_name="info_item_sources",
        schema="information",
    )
