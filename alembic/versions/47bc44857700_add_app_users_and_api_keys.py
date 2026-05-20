"""add app_users and api_keys

Revision ID: 47bc44857700
Revises: 8f2fc3f07976
Create Date: 2026-05-19 16:33:25.549973

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "47bc44857700"
down_revision: str | Sequence[str] | None = "8f2fc3f07976"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NOW = sa.text("now()")


def upgrade() -> None:
    """Create information.app_users and information.api_keys tables."""
    op.create_table(
        "app_users",
        sa.Column("id", sa.String(length=26), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
        schema="information",
    )
    op.create_index(
        op.f("ix_information_app_users_external_id"),
        "app_users",
        ["external_id"],
        unique=True,
        schema="information",
    )
    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(length=26), nullable=False),
        sa.Column("user_id", sa.String(length=26), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("key_prefix", sa.String(length=8), nullable=False),
        sa.Column("key_hash", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["information.app_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="information",
    )
    op.create_index(
        op.f("ix_information_api_keys_user_id"),
        "api_keys",
        ["user_id"],
        unique=False,
        schema="information",
    )


def downgrade() -> None:
    """Drop information.app_users and information.api_keys tables."""
    op.drop_index(
        op.f("ix_information_api_keys_user_id"), table_name="api_keys", schema="information"
    )
    op.drop_table("api_keys", schema="information")
    op.drop_index(
        op.f("ix_information_app_users_external_id"),
        table_name="app_users",
        schema="information",
    )
    op.drop_table("app_users", schema="information")
