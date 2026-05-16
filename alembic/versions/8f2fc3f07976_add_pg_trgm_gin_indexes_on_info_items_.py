"""add pg_trgm GIN indexes on info_items name and description

Revision ID: 8f2fc3f07976
Revises: 3f3bd166961b
Create Date: 2026-05-16 23:19:58.325871

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8f2fc3f07976"
down_revision: str | Sequence[str] | None = "3f3bd166961b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # find_info_item runs ILIKE '%q%' across info_items.name + description; without
    # trigram indexes the planner falls back to sequential scans (archiver#23).
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_index(
        "ix_info_items_name_trgm",
        "info_items",
        ["name"],
        unique=False,
        schema="information",
        postgresql_using="gin",
        postgresql_ops={"name": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_info_items_description_trgm",
        "info_items",
        ["description"],
        unique=False,
        schema="information",
        postgresql_using="gin",
        postgresql_ops={"description": "gin_trgm_ops"},
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_info_items_description_trgm",
        table_name="info_items",
        schema="information",
    )
    op.drop_index(
        "ix_info_items_name_trgm",
        table_name="info_items",
        schema="information",
    )
    # pg_trgm is intentionally left installed; other tables may depend on it.
