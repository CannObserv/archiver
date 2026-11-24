"""rep_spec path_template {source_revision.date} -> {source_revision.date_label}

Revision ID: e4897ee850d9
Revises: c4a9e1f07d2b
Create Date: 2026-11-24 12:00:00.000000

archiver#523 renamed the occasion key ``source_revision.date`` to
``source_revision.date_label``. That is the shared storage vocabulary's name
for the same ``YYYY-MM-DD`` string (cannobserv#703, operator decision
2026-11-17). No alias was kept, so after the rename a stored template that
names the old key would no longer validate or render. This migration rewrites
the old key in every RepSpec's ``path_template``.

**Assigned documents: a recorded #83 exception.** An assigned RepSpec's
``document`` is frozen, and ``PATCH`` refuses the edit. The operator granted
this exception on 2026-11-17 (recorded on archiver#523). It has the same shape
as ``70f32f641751``'s alias rename. An assignment asserts that its artefacts
came from its RepSpec's document, and that still holds, because the rewrite
changes no behaviour: ``date_label`` renders exactly the bytes ``date`` did
(``captured_at`` in UTC, ``isoformat()``), so every destination stays where it
was. Count at authoring, #164's rule [measured 2026-11-24]: production had 0 of
1 RepSpecs with the old key, and ``archiver_dev`` had 0 of 3.

**Scope.** Only ``document->'path_template'``, and only the exact
``{source_revision.date}`` token, braces included. A bare
``source_revision.date`` substring would also match ``date_segment``. Two other
places were checked and left alone:
- ``required_fields`` already refuses the occasion namespace, so it can't hold
  the key;
- ``path_template`` never travels on the bus (``docs/BUS.md``).

``updated_at`` records the edit, as it does for a route edit and for
``70f32f641751``.

**Downgrade reverses it.** Before this revision ``date_label`` was not in the
vocabulary. So any ``{source_revision.date_label}`` seen at downgrade was
written either by this upgrade or under the code this revision ships with.
Either way, the older code can only render it as ``{source_revision.date}``,
and the rendered bytes are the same. That includes a document authored with
``date_label`` after the upgrade and assigned since. Rewriting it is a frozen
edit too, and the same #83 exception covers it for the same reason: no
destination moves.
"""

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e4897ee850d9"
down_revision: str | Sequence[str] | None = "c4a9e1f07d2b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.runtime.migration")

_OLD = "{source_revision.date}"
_NEW = "{source_revision.date_label}"


def _rewrite(old: str, new: str) -> int:
    """Replace ``old`` with ``new`` in every ``path_template`` holding it; return the count.

    ``strpos`` matches a literal string, where ``LIKE`` would treat ``_`` as a
    wildcard. ``replace`` is literal too and replaces every occurrence. Only
    rows that change are touched, so a re-run matches nothing.
    """
    result = op.get_bind().execute(
        sa.text(
            "UPDATE information.rep_specs"
            "   SET document = jsonb_set("
            "         document, '{path_template}',"
            "         to_jsonb(replace(document->>'path_template', :old, :new))"
            "       ),"
            "       updated_at = now()"
            " WHERE strpos(document->>'path_template', :old) > 0"
        ),
        {"old": old, "new": new},
    )
    return result.rowcount


def upgrade() -> None:
    """Rewrite ``{source_revision.date}`` to ``{source_revision.date_label}``."""
    count = _rewrite(_OLD, _NEW)
    logger.info(
        "archiver#523: rewrote %s RepSpec path_template(s) from %s to %s", count, _OLD, _NEW
    )


def downgrade() -> None:
    """Rewrite ``{source_revision.date_label}`` back to ``{source_revision.date}``."""
    count = _rewrite(_NEW, _OLD)
    logger.info(
        "archiver#523 downgrade: rewrote %s RepSpec path_template(s) from %s to %s",
        count,
        _NEW,
        _OLD,
    )
