"""add_domain_name_to_info_sources

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-06-04 00:01:00.000000

Adds nullable FK column ``domain_name`` to ``info_sources`` referencing
``information.domains(name)`` ON DELETE SET NULL. Includes an index on
``domain_name`` to support the domain overview GROUP BY query efficiently.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: str | Sequence[str] | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "info_sources",
        sa.Column("domain_name", sa.String(253), nullable=True),
        schema="information",
    )
    op.create_foreign_key(
        "fk_info_sources_domain_name",
        "info_sources",
        "domains",
        ["domain_name"],
        ["name"],
        source_schema="information",
        referent_schema="information",
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_info_sources_domain_name",
        "info_sources",
        ["domain_name"],
        unique=False,
        schema="information",
    )


def downgrade() -> None:
    op.drop_index("ix_info_sources_domain_name", table_name="info_sources", schema="information")
    op.drop_constraint(
        "fk_info_sources_domain_name",
        "info_sources",
        schema="information",
        type_="foreignkey",
    )
    op.drop_column("info_sources", "domain_name", schema="information")
