"""create rep_specs

Revision ID: 5a08d8e2fc5e
Revises: ed0907b43fbe
Create Date: 2026-05-08 19:42:07.238538

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '5a08d8e2fc5e'
down_revision: str | Sequence[str] | None = 'ed0907b43fbe'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'rep_specs',
        sa.Column('rep_spec_id', sa.String(length=26), nullable=False),
        sa.Column('provider', sa.String(length=50), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('schema_version', sa.Integer(), nullable=False),
        sa.Column('document', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint('rep_spec_id'),
        schema='information',
    )
    op.create_index(
        'ix_rep_specs_provider', 'rep_specs', ['provider'], unique=False, schema='information'
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_rep_specs_provider', table_name='rep_specs', schema='information')
    op.drop_table('rep_specs', schema='information')
