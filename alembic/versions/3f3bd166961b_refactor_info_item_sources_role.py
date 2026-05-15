"""refactor info_item_sources role

Revision ID: 3f3bd166961b
Revises: 9cdd4b999882
Create Date: 2026-05-15 23:04:54.121525

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3f3bd166961b"
down_revision: str | Sequence[str] | None = "9cdd4b999882"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Refactor role: primary becomes implicit (NULL); enum restricted to fragment roles."""
    # 1. Normalize data — pre-prod, so any non-conforming rows are bugs; assert
    #    via a guard query that there are none, then map 'primary' → NULL.
    op.execute(
        """
        DO $$
        DECLARE bad_count int;
        BEGIN
            SELECT count(*) INTO bad_count
              FROM information.info_item_sources
             WHERE role IS NOT NULL AND role NOT IN ('primary', 'cross_check', 'sub_aspect');
            IF bad_count > 0 THEN
                RAISE EXCEPTION
                    'info_item_sources has % rows with non-conforming role values; '
                    'clean them up before applying this migration', bad_count;
            END IF;
        END $$;
        """
    )
    op.execute("UPDATE information.info_item_sources SET role = NULL WHERE role = 'primary'")

    # 2. Drop the old partial-unique (keyed on role='primary')
    op.drop_index(
        "uq_info_item_sources_active_primary",
        table_name="info_item_sources",
        schema="information",
        postgresql_where=sa.text("deactivated_at IS NULL AND role = 'primary'"),
    )

    # 3. Make role nullable + add CHECK on allowed values
    op.alter_column(
        "info_item_sources",
        "role",
        existing_type=sa.String(length=50),
        nullable=True,
        schema="information",
    )
    op.create_check_constraint(
        "ck_info_item_sources_role_values",
        "info_item_sources",
        "role IS NULL OR role IN ('cross_check', 'sub_aspect')",
        schema="information",
    )

    # 4. New partial-unique: at most one active root binding per InfoItem
    op.create_index(
        "uq_info_item_sources_active_root",
        "info_item_sources",
        ["info_item_id"],
        unique=True,
        schema="information",
        postgresql_where=sa.text("deactivated_at IS NULL AND role IS NULL"),
    )


def downgrade() -> None:
    """Reverse the role refactor. Lossy: existing NULL roles become 'primary'."""
    op.drop_index(
        "uq_info_item_sources_active_root",
        table_name="info_item_sources",
        schema="information",
        postgresql_where=sa.text("deactivated_at IS NULL AND role IS NULL"),
    )
    op.drop_constraint(
        "ck_info_item_sources_role_values",
        "info_item_sources",
        type_="check",
        schema="information",
    )
    op.execute("UPDATE information.info_item_sources SET role = 'primary' WHERE role IS NULL")
    op.alter_column(
        "info_item_sources",
        "role",
        existing_type=sa.String(length=50),
        nullable=False,
        schema="information",
    )
    op.create_index(
        "uq_info_item_sources_active_primary",
        "info_item_sources",
        ["info_item_id"],
        unique=True,
        schema="information",
        postgresql_where=sa.text("deactivated_at IS NULL AND role = 'primary'"),
    )
