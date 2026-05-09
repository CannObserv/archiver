"""rename ix_iisr_item_bound_desc to ix_iisr_item_bound

Revision ID: 5b86ae343cb6
Revises: a12c1624655c
Create Date: 2026-05-09 03:35:24.847777

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5b86ae343cb6'
down_revision: Union[str, Sequence[str], None] = 'a12c1624655c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop the misleadingly-named _desc index and recreate without the suffix.

    The original index was created with `Index(... "info_item_id", "bound_at")` —
    the trailing `_desc` was a misnomer (no DESC ordering applied). This rename
    aligns the index name with its actual ascending shape.
    """
    op.execute(
        "ALTER INDEX information.ix_iisr_item_bound_desc "
        "RENAME TO ix_iisr_item_bound"
    )


def downgrade() -> None:
    """Restore the original (misleading) name."""
    op.execute(
        "ALTER INDEX information.ix_iisr_item_bound "
        "RENAME TO ix_iisr_item_bound_desc"
    )
