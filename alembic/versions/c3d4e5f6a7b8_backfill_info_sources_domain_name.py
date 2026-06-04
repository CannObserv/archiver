"""backfill_info_sources_domain_name

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-06-04 00:02:00.000000

Data migration: for each existing info_source row, extract the hostname from
``url`` using PostgreSQL string functions, upsert a domain row, and set
``domain_name``. Kept separate from the schema migration for auditability.
"""

from collections.abc import Sequence
from datetime import UTC, datetime

from alembic import op
from sqlalchemy import text
from ulid import ULID

revision: str = "c3d4e5f6a7b8"
down_revision: str | Sequence[str] | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EXTRACT_HOST = r"substring(url from '://([^/?#]+)')"


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Collect distinct hostnames from existing info_sources
    rows = conn.execute(
        text(
            f"SELECT DISTINCT {_EXTRACT_HOST} AS hostname"
            f" FROM information.info_sources"
            f" WHERE {_EXTRACT_HOST} IS NOT NULL"
        )
    ).fetchall()

    now = datetime.now(UTC)
    for (hostname,) in rows:
        conn.execute(
            text(
                "INSERT INTO information.domains (id, name, is_active, created_at, updated_at) "
                "VALUES (:id, :name, true, :now, :now) "
                "ON CONFLICT (name) DO NOTHING"
            ),
            {"id": str(ULID()), "name": hostname, "now": now},
        )

    # 2. Backfill domain_name on info_sources
    conn.execute(
        text(
            f"UPDATE information.info_sources "
            f"SET domain_name = {_EXTRACT_HOST} "
            f"WHERE domain_name IS NULL AND {_EXTRACT_HOST} IS NOT NULL"
        )
    )


def downgrade() -> None:
    op.execute(text("UPDATE information.info_sources SET domain_name = NULL"))
