"""drop sub_aspect role from info_item_sources

Revision ID: b1c2d3e4f5a6
Revises: 47bc44857700
Create Date: 2026-06-02 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "b1c2d3e4f5a6"
down_revision: str | Sequence[str] | None = "47bc44857700"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Narrow the role CHECK constraint to only allow NULL and 'cross_check'."""
    op.execute(
        """
        DO $$
        DECLARE bad_count int;
        BEGIN
            SELECT count(*) INTO bad_count
              FROM information.info_item_sources
             WHERE role = 'sub_aspect';
            IF bad_count > 0 THEN
                RAISE EXCEPTION
                    'info_item_sources has % rows with role=sub_aspect; '
                    'migrate or delete them before applying this migration', bad_count;
            END IF;
        END $$;
        """
    )
    op.drop_constraint(
        "ck_info_item_sources_role_values",
        "info_item_sources",
        type_="check",
        schema="information",
    )
    op.create_check_constraint(
        "ck_info_item_sources_role_values",
        "info_item_sources",
        "role IS NULL OR role IN ('cross_check')",
        schema="information",
    )


def downgrade() -> None:
    """Restore the broader CHECK constraint that included sub_aspect."""
    op.drop_constraint(
        "ck_info_item_sources_role_values",
        "info_item_sources",
        type_="check",
        schema="information",
    )
    op.create_check_constraint(
        "ck_info_item_sources_role_values",
        "info_item_sources",
        "role IS NULL OR role IN ('cross_check', 'sub_aspect')",
        schema="information",
    )
