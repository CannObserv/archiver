"""domains.fetch_policy_generation and fetch_policy_tombstones

Revision ID: 44b797877fdb
Revises: 173c1af91def
Create Date: 2026-10-26 12:00:00.000000

archiver#366: Archiver produces ``content.fetch-policy`` (dark until flip F1),
and every frame carries a ``generation`` (cannobserv#566). It comes from one
sequence, never a per-row counter: a hostname is a reusable natural key, so a
re-added host must draw above its own tombstone.

Adding the column with a ``nextval`` default backfills every existing row
with a distinct value, since Postgres evaluates a volatile default per row.

**Expand-only** (archiver#330 D3): the previous release's ORM inserts domains
without the column; the server default takes them. It never reads the new
table.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "44b797877fdb"
down_revision: str | Sequence[str] | None = "173c1af91def"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMA = "information"
_SEQ = "fetch_policy_generation_seq"


def upgrade() -> None:
    """Create the sequence, the generation column (backfilled) and the tombstone table."""
    op.execute(sa.schema.CreateSequence(sa.Sequence(_SEQ, schema=_SCHEMA)))
    op.add_column(
        "domains",
        sa.Column(
            "fetch_policy_generation",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text(f"nextval('{_SCHEMA}.{_SEQ}'::regclass)"),
        ),
        schema=_SCHEMA,
    )
    op.create_table(
        "fetch_policy_tombstones",
        sa.Column("host", sa.Text(), primary_key=True),
        sa.Column("generation", sa.BigInteger(), nullable=False),
        sa.Column(
            "revoked_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema=_SCHEMA,
    )


def downgrade() -> None:
    """Drop them. Lossy past F1: a re-upgrade restarts the sequence at 1, below
    every generation already on the wire, and consumers skip each host until
    those frames trim out (co-core ``FetchPolicyState`` obligation 3)."""
    op.drop_table("fetch_policy_tombstones", schema=_SCHEMA)
    op.drop_column("domains", "fetch_policy_generation", schema=_SCHEMA)
    op.execute(sa.schema.DropSequence(sa.Sequence(_SEQ, schema=_SCHEMA)))
