"""The schema check: the database's Alembic revision against the code's head (archiver#330 D3).

Ported from CannObserv/status R8 (``src/core/schema_state.py`` there). Once
production runs releases, a release and its database can disagree in two
directions, and only one of them is a fault:

- ``behind`` / ``unmigrated`` - the code expects a migration that has not run.
  The 2026-09-29 status incident: new code against an old schema.
- ``ahead`` - the database carries a revision this code does not know. That is
  what a rollback looks like (older release, newer schema), and the
  expand-only rule (design D3, status R7) makes it safe to serve.

Nothing here refuses a start (broker#22 goal 3). The CLI answers
``scripts/deploy.sh``, which migrates only on a state it printed and skips the
migration on ``ahead``; ``archiver-bus-health`` WARNs on a state that cannot
serve. Unlike status there is no ``/ready``: only ``/health`` and
``/openapi.json`` may be open here, and ``/health`` stays DB-free.

The CLI's exit codes: 0 for ``current`` or ``ahead``, 3 for ``behind`` or
``unmigrated``, 2 for anything else (refused by ``db_safety``, unreachable,
crashed). Never 1, which Python uses for an uncaught exception.
"""

from __future__ import annotations

import argparse
import asyncio
import enum
import os
import sys
from pathlib import Path
from typing import Protocol

from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from src.core.database import get_database_url
from src.core.db_safety import ALLOW_PRODUCTION_DB_ENV, assert_production_db_allowed

#: The release (or checkout) root: the project is installed editable, so this
#: module sits at ``<root>/src/core/``.
ROOT = Path(__file__).resolve().parents[2]

#: ``alembic/env.py`` keeps its version table in the ``information`` schema.
VERSION_SCHEMA = "information"

EXIT_OK = 0
EXIT_ERROR = 2
EXIT_BEHIND = 3


class SchemaState(enum.Enum):
    """Where the database stands relative to this code's single head."""

    CURRENT = "current"
    BEHIND = "behind"
    AHEAD = "ahead"
    UNMIGRATED = "unmigrated"

    @property
    def can_serve(self) -> bool:
        """``ahead`` serves too: by the expand-only rule, older code runs on a newer schema."""
        return self in (SchemaState.CURRENT, SchemaState.AHEAD)


class MultipleHeadsError(RuntimeError):
    """The Alembic chain has more than one head, so "behind" has no meaning."""


class _Heads(Protocol):
    def get_heads(self) -> list[str]: ...


def _script() -> ScriptDirectory:
    return ScriptDirectory(str(ROOT / "alembic"))


def code_head(script: _Heads | None = None) -> str:
    """The code's single Alembic head; refuses more than one."""
    heads = (script or _script()).get_heads()
    if len(heads) != 1:
        raise MultipleHeadsError(f"expected one Alembic head, found {len(heads)}: {sorted(heads)}")
    return heads[0]


def known_revisions() -> frozenset[str]:
    """Every revision this code's chain contains."""
    return frozenset(rev.revision for rev in _script().walk_revisions())


async def database_revision(conn: AsyncConnection, *, schema: str = VERSION_SCHEMA) -> str | None:
    """The database's revision, or None when it has no version table (or no row).

    ``to_regclass`` returns NULL for a missing relation instead of raising, so
    the probe never aborts the caller's transaction.
    """
    table = f"{schema}.alembic_version"
    exists = (await conn.execute(text("SELECT to_regclass(:t)"), {"t": table})).scalar()
    if exists is None:
        return None
    return (await conn.execute(text(f"SELECT version_num FROM {table}"))).scalar()


def classify(db_revision: str | None, *, head: str, known: frozenset[str]) -> SchemaState:
    """Pure: the state of a database at ``db_revision`` for code at ``head``."""
    if db_revision is None:
        return SchemaState.UNMIGRATED
    if db_revision == head:
        return SchemaState.CURRENT
    if db_revision in known:
        return SchemaState.BEHIND
    return SchemaState.AHEAD


async def probe(url: str) -> tuple[SchemaState, str | None, str]:
    """Connect once, read the revision, classify. Returns (state, db revision, code head)."""
    head = code_head()
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            rev = await database_revision(conn)
    finally:
        await engine.dispose()
    return classify(rev, head=head, known=known_revisions()), rev, head


def main(argv: list[str] | None = None) -> int:
    """Print ``<state> database=<rev> code=<head>`` and exit 0, 3 or 2."""
    parser = argparse.ArgumentParser(
        prog="python -m src.core.schema_state",
        description="Compare the database's Alembic revision with this code's head.",
    )
    parser.parse_args(argv)
    try:
        url = get_database_url()
        assert_production_db_allowed(url, allow_flag=os.environ.get(ALLOW_PRODUCTION_DB_ENV))
        state, rev, head = asyncio.run(probe(url))
    except Exception as e:  # noqa: BLE001 - every failure is exit 2, named on stderr
        print(f"schema_state: {e}", file=sys.stderr)
        return EXIT_ERROR
    print(f"{state.value} database={rev or '-'} code={head}")
    return EXIT_OK if state.can_serve else EXIT_BEHIND


if __name__ == "__main__":
    sys.exit(main())
