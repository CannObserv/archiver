"""drop info_specs

Revision ID: d932fbc8d1cd
Revises: 938ebc034b82
Create Date: 2026-05-08 18:46:36.705503

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d932fbc8d1cd"
down_revision: str | Sequence[str] | None = "938ebc034b82"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Drop info_specs table (Phase 4 v2 cutover)."""
    op.drop_table("info_specs", schema="information")


def downgrade() -> None:
    """Downgrade not supported — Phase 4 cutover is one-way.

    Restore from the prior migration if you really need to revert.
    """
    raise NotImplementedError(
        "Phase 4 cutover is one-way; restore from prior migration if needed"
    )
