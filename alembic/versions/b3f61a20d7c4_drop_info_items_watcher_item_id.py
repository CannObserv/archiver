"""drop info_items.watcher_item_id

The last structural trace of the Archiver→Watcher HTTP edge (archiver#142).

The column held *Watcher's* primary key on an *Archiver* row — a coupling
artifact, and the thing the decoupling epic (#137) set out to remove. Under
announcements the key is Archiver's own ``info_item_id`` and Watcher reconciles
against that, so nothing allocates a WatchedItem id to store: ``provision_on_create``
was the only writer, and it went with the SDK.

Safe to drop now because the reads went first, in the same wave:

- the watched-item panel's state key moved to announceability (an active binding
  whose source carries non-empty ``source_specs``) — keeping this column as the
  key would have reported ``not_watching`` for every announced item;
- the delete route's orphan warning re-keyed onto the ``watch_status`` row, which
  is evidence from Watcher rather than a stale local pointer;
- the per-item Watcher deeplink retired, having no target without this id.

**Irreversible in practice.** ``downgrade()`` restores the column, but not its
values: Watcher's ids were never recorded anywhere else, and the only reader that
could have re-fetched them is deleted. Restoring the shape gets an all-NULL
column, which is exactly what a post-cutover registry would hold anyway.

Revision ID: b3f61a20d7c4
Revises: e3a71c40b9d2
Create Date: 2026-08-17

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b3f61a20d7c4"
down_revision: str | None = "e3a71c40b9d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("info_items", "watcher_item_id", schema="information")


def downgrade() -> None:
    # Shape only — the values are unrecoverable (see the module docstring).
    op.add_column(
        "info_items",
        sa.Column("watcher_item_id", sa.String(length=50), nullable=True),
        schema="information",
    )
