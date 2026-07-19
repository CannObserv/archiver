"""restore ix_info_sources_domain_name

Three read paths filter or group by ``info_sources.domain_name``: the domain
detail page's source listing, its heading COUNT (#82), and the domain list's
GROUP BY. The index was dropped in fff827419c6c together with the
``fk_info_sources_domain_name`` foreign key, as ORM/DB alignment cleanup after
#48 removed both from the model — not because the index was unwanted. Restore
the index only; the FK stays dropped, which remains a deliberate model decision.

The table is small enough that a plain CREATE INDEX is fine. If it grows large
before this ships anywhere else, switch to ``postgresql_concurrently=True``
(which additionally requires the migration to run outside a transaction).

Revision ID: fa99ef9f1dbd
Revises: fff827419c6c
Create Date: 2026-07-19 00:36:55.754065

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "fa99ef9f1dbd"
down_revision: str | Sequence[str] | None = "fff827419c6c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index(
        "ix_info_sources_domain_name",
        "info_sources",
        ["domain_name"],
        unique=False,
        schema="information",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_info_sources_domain_name", table_name="info_sources", schema="information")
