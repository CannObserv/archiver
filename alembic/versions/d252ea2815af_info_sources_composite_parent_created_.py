"""info_sources composite parent+created index for pagination

Revision ID: d252ea2815af
Revises: 5b86ae343cb6
Create Date: 2026-05-11 01:11:31.033824

Replaces the parent-only partial index ``ix_info_sources_parent`` with a
composite ``(parent_info_source_id, created_at, info_source_id)`` so that
paginated fragment reads — ``WHERE parent_info_source_id = X ORDER BY
created_at, info_source_id LIMIT ... OFFSET ...`` (Watcher Phase 5 hot path)
— satisfy filter + sort + tiebreaker from a single index lookup.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d252ea2815af"
down_revision: str | Sequence[str] | None = "5b86ae343cb6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index(
        "ix_info_sources_parent",
        table_name="info_sources",
        schema="information",
        postgresql_where="parent_info_source_id IS NOT NULL",
    )
    op.create_index(
        "ix_info_sources_parent_created",
        "info_sources",
        ["parent_info_source_id", "created_at", "info_source_id"],
        unique=False,
        schema="information",
        postgresql_where="parent_info_source_id IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_info_sources_parent_created",
        table_name="info_sources",
        schema="information",
        postgresql_where="parent_info_source_id IS NOT NULL",
    )
    op.create_index(
        "ix_info_sources_parent",
        "info_sources",
        ["parent_info_source_id"],
        unique=False,
        schema="information",
        postgresql_where="parent_info_source_id IS NOT NULL",
    )
