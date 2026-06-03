"""info_source simplification: source_specs array, url column, drop fragments and role

Revision ID: c9d8e7f6a5b4
Revises: b1c2d3e4f5a6
Create Date: 2026-06-03 00:00:00.000000

Changes:
- info_sources: add url (TEXT NOT NULL), add source_specs (JSONB NOT NULL array),
  drop source_spec, drop schema_version, drop parent_info_source_id,
  drop XOR check constraint, drop uq_info_sources_url unique constraint,
  drop ix_info_sources_parent_created, add ix_info_sources_url plain index.
- info_item_sources: drop role column, drop CHECK constraint,
  rename unique index from active_root to active (condition simplified).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "c9d8e7f6a5b4"
down_revision: str | Sequence[str] | None = "b1c2d3e4f5a6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------ guards
    op.execute(
        """
        DO $$
        DECLARE bad_count int;
        BEGIN
            SELECT count(*) INTO bad_count
              FROM information.info_sources
             WHERE parent_info_source_id IS NOT NULL;
            IF bad_count > 0 THEN
                RAISE EXCEPTION
                    'info_sources has % fragment rows (parent_info_source_id IS NOT NULL); '
                    'remove them before applying this migration', bad_count;
            END IF;
        END $$;
        """
    )
    op.execute(
        """
        DO $$
        DECLARE bad_count int;
        BEGIN
            SELECT count(*) INTO bad_count
              FROM information.info_item_sources
             WHERE role IS NOT NULL;
            IF bad_count > 0 THEN
                RAISE EXCEPTION
                    'info_item_sources has % rows with non-null role; '
                    'remove them before applying this migration', bad_count;
            END IF;
        END $$;
        """
    )

    # ------------------------------------------------- info_sources: new cols
    # source_specs: wrap existing source_spec into single-element JSONB array
    op.add_column(
        "info_sources",
        sa.Column("source_specs", JSONB, nullable=True),
        schema="information",
    )
    op.execute("UPDATE information.info_sources SET source_specs = jsonb_build_array(source_spec)")
    op.alter_column("info_sources", "source_specs", nullable=False, schema="information")

    # url: promote from computed column to real column
    # The computed column is already persisted with the correct value; we add a
    # new real column, copy the values, then drop the old computed one.
    op.add_column(
        "info_sources",
        sa.Column("url_new", sa.Text, nullable=True),
        schema="information",
    )
    op.execute("UPDATE information.info_sources SET url_new = url")
    op.alter_column("info_sources", "url_new", nullable=False, schema="information")

    # --------------------------------- info_sources: drop old constraints/cols
    # Drop unique constraint on url before dropping the computed column
    op.drop_constraint("uq_info_sources_url", "info_sources", type_="unique", schema="information")
    # Drop fragment pagination index
    op.drop_index(
        "ix_info_sources_parent_created",
        table_name="info_sources",
        schema="information",
    )
    # Drop XOR check constraint
    op.drop_constraint(
        "ck_info_sources_root_xor_fragment",
        "info_sources",
        type_="check",
        schema="information",
    )
    # Drop the FK on parent_info_source_id before dropping the column
    op.drop_constraint(
        "info_sources_parent_info_source_id_fkey",
        "info_sources",
        type_="foreignkey",
        schema="information",
    )
    op.drop_column("info_sources", "parent_info_source_id", schema="information")
    op.drop_column("info_sources", "schema_version", schema="information")
    # Drop computed url column and rename url_new → url
    op.drop_column("info_sources", "url", schema="information")
    op.drop_column("info_sources", "source_spec", schema="information")
    op.alter_column(
        "info_sources",
        "url_new",
        new_column_name="url",
        schema="information",
    )

    # Add plain url index for lookup
    op.create_index(
        "ix_info_sources_url",
        "info_sources",
        ["url"],
        schema="information",
    )

    # ------------------------------------------ info_item_sources: drop role
    op.drop_constraint(
        "ck_info_item_sources_role_values",
        "info_item_sources",
        type_="check",
        schema="information",
    )
    op.drop_index(
        "uq_info_item_sources_active_root",
        table_name="info_item_sources",
        schema="information",
        postgresql_where=sa.text("deactivated_at IS NULL AND role IS NULL"),
    )
    op.drop_column("info_item_sources", "role", schema="information")
    op.create_index(
        "uq_info_item_sources_active",
        "info_item_sources",
        ["info_item_id"],
        unique=True,
        schema="information",
        postgresql_where=sa.text("deactivated_at IS NULL"),
    )


def downgrade() -> None:
    """Reverse is destructive — fragment rows and role values cannot be recovered."""
    # info_item_sources
    op.drop_index(
        "uq_info_item_sources_active",
        table_name="info_item_sources",
        schema="information",
        postgresql_where=sa.text("deactivated_at IS NULL"),
    )
    op.add_column(
        "info_item_sources",
        sa.Column("role", sa.String(length=50), nullable=True),
        schema="information",
    )
    op.create_index(
        "uq_info_item_sources_active_root",
        "info_item_sources",
        ["info_item_id"],
        unique=True,
        schema="information",
        postgresql_where=sa.text("deactivated_at IS NULL AND role IS NULL"),
    )
    op.create_check_constraint(
        "ck_info_item_sources_role_values",
        "info_item_sources",
        "role IS NULL OR role IN ('cross_check')",
        schema="information",
    )

    # info_sources — best-effort reconstruction
    op.drop_index("ix_info_sources_url", table_name="info_sources", schema="information")
    op.add_column(
        "info_sources",
        sa.Column("schema_version", sa.Integer, nullable=True),
        schema="information",
    )
    op.add_column(
        "info_sources",
        sa.Column("parent_info_source_id", sa.Text, nullable=True),
        schema="information",
    )
    op.add_column(
        "info_sources",
        sa.Column("source_spec", JSONB, nullable=True),
        schema="information",
    )
    op.execute(
        "UPDATE information.info_sources "
        "SET source_spec = source_specs->0, "
        "    schema_version = (source_specs->0->>'schema_version')::int"
    )
    op.drop_column("info_sources", "source_specs", schema="information")
    op.drop_column("info_sources", "url", schema="information")
