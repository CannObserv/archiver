"""The production read role's grants, as code (archiver#348).

Agents read production as Postgres role ``exedev``: peer-authenticated over
the Unix socket, no password anywhere (#348 option A). A superuser creates the
role and sets its limits once (``docs/plans/2026-10-11-348-prod-read-access.md``);
everything it may read is granted here, by the tables' owner, and
``scripts/deploy.sh`` re-applies it after every migration on both databases.

Read-only by privilege: the role is granted ``SELECT`` and nothing else.
Every table in the schema is readable, and default privileges make a table a
later migration creates readable too, except the restricted ones: there the
role reads an explicit column allowlist, so personal data and the key hash
stay out and a column added later starts withheld. A migration that recreates
a restricted table hands it a whole-table grant through the default
privileges; the next application, at the end of that same deploy, takes it back.

The CLI prints one line and exits 0 when it applied the grants or the role is
absent (CI, or a host without it), 2 on anything else. ``--sql`` prints the
statements for a superuser session instead, connecting to nothing.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from typing import NamedTuple

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from src.core.database import get_database_url
from src.core.db_safety import ALLOW_PRODUCTION_DB_ENV, assert_production_db_allowed

#: The OS user agents run as; ``local all all peer`` maps it to this role.
READER_ROLE = "exedev"

SCHEMA = "information"

CONNECT_TIMEOUT_SECONDS = 10

EXIT_OK = 0
EXIT_ERROR = 2

_IDENTIFIER = re.compile(r"[a-z_][a-z0-9_]*\Z")


class Restriction(NamedTuple):
    """A table the role reads by column: every column is one or the other."""

    readable: tuple[str, ...]
    withheld: tuple[str, ...]


RESTRICTED: dict[str, Restriction] = {
    "app_users": Restriction(
        readable=("id", "created_at", "updated_at"),
        withheld=("external_id", "email"),
    ),
    "api_keys": Restriction(
        readable=("id", "user_id", "label", "key_prefix", "created_at", "last_used_at"),
        withheld=("key_hash",),
    ),
}


def _identifier(name: str, what: str) -> str:
    # PUBLIC is for the tests alone: archiver_agent cannot create a role, so they
    # grant to PUBLIC and roll back. Production always passes READER_ROLE.
    if name != "PUBLIC" and not _IDENTIFIER.match(name):
        raise ValueError(f"{what} {name!r} is not a plain identifier")
    return name


def grant_statements(database: str, role: str = READER_ROLE) -> list[str]:
    """The grant set for ``role`` on ``database``, as one transaction.

    A table-level ``SELECT`` overrides column privileges, so a restricted table
    loses its table-level grant (which takes its column grants with it) and
    gets the allowlist back.
    """
    role = _identifier(role, "role")
    database = _identifier(database, "database")
    statements = [
        "BEGIN",
        f"GRANT CONNECT ON DATABASE {database} TO {role}",
        f"GRANT USAGE ON SCHEMA {SCHEMA} TO {role}",
        f"GRANT SELECT ON ALL TABLES IN SCHEMA {SCHEMA} TO {role}",
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA {SCHEMA} GRANT SELECT ON TABLES TO {role}",
    ]
    for table, restriction in RESTRICTED.items():
        columns = ", ".join(restriction.readable)
        statements += [
            f"REVOKE SELECT ON {SCHEMA}.{table} FROM {role}",
            f"GRANT SELECT ({columns}) ON {SCHEMA}.{table} TO {role}",
        ]
    return [*statements, "COMMIT"]


async def role_exists(conn: AsyncConnection, role: str) -> bool:
    """Whether the cluster has ``role``."""
    found = await conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role})
    return found.scalar() is not None


async def apply_grants(conn: AsyncConnection, role: str) -> None:
    """Apply the grant set inside the caller's transaction, as the tables' owner."""
    database = (await conn.execute(text("SELECT current_database()"))).scalar()
    for statement in grant_statements(database, role)[1:-1]:
        await conn.execute(text(statement))


async def _apply(url: str, role: str) -> str:
    engine = create_async_engine(url, connect_args={"timeout": CONNECT_TIMEOUT_SECONDS})
    try:
        async with engine.begin() as conn:
            if not await role_exists(conn, role):
                return f"{role} absent: no grants"
            await apply_grants(conn, role)
            database = (await conn.execute(text("SELECT current_database()"))).scalar()
    finally:
        await engine.dispose()
    return f"granted {role} read access to {database}"


def main(argv: list[str] | None = None) -> int:
    """Apply the grants (or print them with ``--sql``); exit 0 or 2."""
    parser = argparse.ArgumentParser(
        prog="python -m src.core.reader_grants",
        description="Grant the production read role what it may read (archiver#348).",
    )
    parser.add_argument(
        "--sql", action="store_true", help="print the statements; connect to nothing"
    )
    parser.add_argument(
        "--database", default="archiver", help="the database --sql grants CONNECT on"
    )
    args = parser.parse_args(argv)
    if args.sql:
        print(";\n".join(grant_statements(args.database, READER_ROLE)) + ";")
        return EXIT_OK
    try:
        url = get_database_url()
        assert_production_db_allowed(url, allow_flag=os.environ.get(ALLOW_PRODUCTION_DB_ENV))
        print(f"reader_grants: {asyncio.run(_apply(url, READER_ROLE))}")
    except Exception as e:  # noqa: BLE001 - every failure is exit 2, named on stderr
        print(f"reader_grants: {e}", file=sys.stderr)
        return EXIT_ERROR
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
