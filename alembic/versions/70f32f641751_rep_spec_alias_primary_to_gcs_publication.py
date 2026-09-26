"""rep_spec credentials_alias primary -> gcs-publication

Revision ID: 70f32f641751
Revises: e964909e0c62
Create Date: 2026-09-26 12:00:00.000000

archiver#276 decision 7: take production's RepSpec off the pre-rule alias
``primary`` before Replicator's 2026-12-31 deadline (replicator#114).

**Why a migration and not ``PATCH /rep-specs/{id}``.** The RepSpec is assigned,
so #83 froze its ``document`` and the route refuses the edit. Clone and migrate
(#95) is still open, and it is a lot of machinery for one row. This is the one
recorded exception to #83 (see its ADR).

**Why this preserves #83's promise.** An assignment row asserts that its
artefacts came from its RepSpec's document. That still holds because the
rewrite changes no behaviour. Since the publication cutover (replicator#114
plan step 4, 2026-09-25 22:53Z), Replicator binds ``primary`` and
``gcs-publication`` to the same bucket (``co-gcs-publication``), with the same
writer identity and the same empty prefix. So a document naming either one
renders every destination to the same object. Artefacts written earlier under
``primary`` into ``co-gcs-replication`` keep resolving: that bucket is frozen,
not moved, and ``public_url`` records where each one landed.

**Scope:** ``gcs`` RepSpecs whose alias is exactly ``primary``. ``primary``
only ever meant a gcs binding. A document of another provider naming it is a
different fault, and giving it a gcs alias would add a provider mismatch. Only
``credentials_alias`` changes. ``updated_at`` records the edit, as it does for
a draft edit through the route. ``replication_commands.credentials_alias`` is
left alone: it records what each command actually sent.

Downgrade is a no-op. Once the rewrite has run, nothing tells a rewritten row
apart from one authored as ``gcs-publication``. Reinstating ``primary`` would
also restore a name Replicator is retiring.
"""

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "70f32f641751"
down_revision: str | Sequence[str] | None = "e964909e0c62"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.runtime.migration")


def upgrade() -> None:
    """Rewrite ``primary`` to ``gcs-publication``. Idempotent: a re-run matches nothing."""
    result = op.get_bind().execute(
        sa.text(
            "UPDATE information.rep_specs"
            "   SET document = jsonb_set(document, '{credentials_alias}', '\"gcs-publication\"'),"
            "       updated_at = now()"
            " WHERE provider = 'gcs'"
            "   AND document->>'credentials_alias' = 'primary'"
        )
    )
    logger.info(
        "archiver#276: moved %s gcs RepSpec(s) from alias primary to gcs-publication",
        result.rowcount,
    )


def downgrade() -> None:
    """No-op: a rewritten alias is indistinguishable from an authored one."""
