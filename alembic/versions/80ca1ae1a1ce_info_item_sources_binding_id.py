"""info_item_sources: one row per tenure, keyed by a ULID id

Revision ID: 80ca1ae1a1ce
Revises: 43c76bf61952
Create Date: 2026-10-17 00:30:00.000000

archiver#392. The composite ``(info_item_id, info_source_id)`` primary key held
one row per pair, so a swap back to a previous primary (#45) could only
reactivate that row, overwriting the first tenure's ``deactivated_at``. A
surrogate ``id`` lets every tenure keep its own row.

The backfill mints each ``id`` from the row's ``created_at``, so the new key
sorts bindings in the order they were made. ``ix_info_item_sources_item``
replaces the composite key's leading column for lookups by item (every
binding of an item; the ``ON DELETE CASCADE`` from ``info_items``).
``uq_info_item_sources_active`` is untouched: still one active primary per item.

The downgrade is refused once any pair has two rows, since the composite key
cannot hold them.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from ulid import ULID

# revision identifiers, used by Alembic.
revision: str = "80ca1ae1a1ce"
down_revision: str | Sequence[str] | None = "43c76bf61952"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "info_item_sources"
_SCHEMA = "information"
_PKEY = "info_item_sources_pkey"
_ITEM_INDEX = "ix_info_item_sources_item"


def upgrade() -> None:
    """Add ``id``, backfill it from ``created_at``, and make it the primary key."""
    op.add_column(_TABLE, sa.Column("id", sa.String(length=26), nullable=True), schema=_SCHEMA)
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            f"SELECT info_item_id, info_source_id, created_at FROM {_SCHEMA}.{_TABLE}"
            " ORDER BY created_at, info_item_id, info_source_id"
        )
    ).all()
    for info_item_id, info_source_id, created_at in rows:
        conn.execute(
            sa.text(
                f"UPDATE {_SCHEMA}.{_TABLE} SET id = :id"
                " WHERE info_item_id = :item AND info_source_id = :source"
            ),
            {
                "id": str(ULID.from_datetime(created_at)),
                "item": info_item_id,
                "source": info_source_id,
            },
        )
    op.alter_column(_TABLE, "id", nullable=False, schema=_SCHEMA)
    op.drop_constraint(_PKEY, _TABLE, type_="primary", schema=_SCHEMA)
    op.create_primary_key(_PKEY, _TABLE, ["id"], schema=_SCHEMA)
    op.create_index(_ITEM_INDEX, _TABLE, ["info_item_id"], schema=_SCHEMA)


def downgrade() -> None:
    """Restore the composite key; refused once a pair holds more than one tenure."""
    op.execute(
        f"""
        DO $$
        DECLARE pairs int;
        BEGIN
            SELECT count(*) INTO pairs FROM (
                SELECT 1 FROM {_SCHEMA}.{_TABLE}
                 GROUP BY info_item_id, info_source_id
                HAVING count(*) > 1
            ) AS repeated;
            IF pairs > 0 THEN
                RAISE EXCEPTION
                    '% (item, source) pairs hold more than one tenure; the composite '
                    'key cannot hold them', pairs;
            END IF;
        END $$;
        """
    )
    op.drop_index(_ITEM_INDEX, table_name=_TABLE, schema=_SCHEMA)
    op.drop_constraint(_PKEY, _TABLE, type_="primary", schema=_SCHEMA)
    op.create_primary_key(_PKEY, _TABLE, ["info_item_id", "info_source_id"], schema=_SCHEMA)
    op.drop_column(_TABLE, "id", schema=_SCHEMA)
