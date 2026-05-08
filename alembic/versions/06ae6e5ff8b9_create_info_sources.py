"""create info_sources

Revision ID: 06ae6e5ff8b9
Revises: a98c7ba01dc6
Create Date: 2026-05-08 19:13:20.601807

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '06ae6e5ff8b9'
down_revision: Union[str, Sequence[str], None] = 'a98c7ba01dc6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create information.info_sources table."""
    op.create_table(
        'info_sources',
        sa.Column('info_source_id', sa.String(length=26), nullable=False),
        sa.Column('parent_info_source_id', sa.String(length=26), nullable=True),
        sa.Column('source_spec', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('schema_version', sa.Integer(), nullable=False),
        sa.Column('url', sa.Text(), sa.Computed("(source_spec->'target'->>'url')", persisted=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('(parent_info_source_id IS NULL) != (url IS NULL)', name='ck_info_sources_root_xor_fragment'),
        sa.ForeignKeyConstraint(['parent_info_source_id'], ['information.info_sources.info_source_id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('info_source_id'),
        sa.UniqueConstraint('url', name='uq_info_sources_url'),
        schema='information',
    )
    op.create_index(
        'ix_info_sources_parent',
        'info_sources',
        ['parent_info_source_id'],
        unique=False,
        schema='information',
        postgresql_where='parent_info_source_id IS NOT NULL',
    )


def downgrade() -> None:
    """Drop information.info_sources table."""
    op.drop_index('ix_info_sources_parent', table_name='info_sources', schema='information', postgresql_where='parent_info_source_id IS NOT NULL')
    op.drop_table('info_sources', schema='information')
