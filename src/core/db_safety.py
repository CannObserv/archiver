"""Production-database startup guard.

Why this exists (archiver, 2026-07-18 incident): the documented dev-server
recipe sourced ``/etc/archiver/.env`` and then ran uvicorn directly, so
``ARCHIVER_DATABASE_URL`` stayed pointed at production. The dev server on 8021
and the live service on 8020 shared one database, and a dashboard verification
run wrote a ``verify79.example.com`` Domain, two InfoSources, and an AppUser
into the production registry.

``scripts/dev_server.sh`` fixes the sanctioned launch path. This module is the
backstop, because a docs-side fix has the same failure mode as the docs bug it
patches: a hand-rolled uvicorn, or a stale recipe copied out of an old plan
doc, still reaches production. The guard lives in the application, so it holds
no matter how the process was started.

The rule is a *positive* assertion, not a comparison against known production
URLs. Comparing URL strings is defeated by cosmetic differences — the same
database is reachable as ``postgresql://…/archiver`` and
``postgresql+asyncpg://…/archiver``, via ``localhost`` or ``127.0.0.1``. The
database *name* is the boundary that actually holds: it must carry a ``_test``
or ``_dev`` suffix, or the caller must opt in explicitly via
``ARCHIVER_ALLOW_PRODUCTION_DB=1`` — which only ``deploy/archiver.service``
does.
"""

from urllib.parse import urlsplit

#: Suffixes that mark a database as disposable. AGENTS.md already documents the
#: ``_test`` convention for TEST_DATABASE_URL; this enforces it.
NON_PRODUCTION_SUFFIXES = ("_test", "_dev")

#: Env var the systemd unit sets to serve the production registry.
ALLOW_PRODUCTION_DB_ENV = "ARCHIVER_ALLOW_PRODUCTION_DB"


class ProductionDatabaseRefused(RuntimeError):
    """Raised when a process would serve production without opting in."""


def database_name(url: str) -> str | None:
    """Return the database name from a SQLAlchemy/libpq URL, or None.

    Returns None when the name cannot be determined, so callers can fail
    closed rather than guess.
    """
    if not url:
        return None
    try:
        # urlsplit handles the credentials, port, and query string, so a
        # password containing an escaped slash cannot be mistaken for a path.
        parts = urlsplit(url)
    except ValueError:
        return None
    # Without a scheme and host this is not a connection URL at all —
    # urlsplit would hand back the whole string as `path`, which would then
    # sail through a naive suffix check.
    if not parts.scheme or not parts.netloc:
        return None
    # A bare host with no path, or a trailing slash, yields an empty name.
    return parts.path.lstrip("/") or None


def is_non_production_database(url: str) -> bool:
    """True when the URL's database name is marked disposable.

    Suffix match, not substring: ``test_archiver`` and ``archiver_testing``
    are production-looking near-misses and must not pass.
    """
    name = database_name(url)
    if name is None:
        return False
    return name.endswith(NON_PRODUCTION_SUFFIXES)


def assert_production_db_allowed(url: str, *, allow_flag: str | None) -> None:
    """Raise ``ProductionDatabaseRefused`` for an un-opted-in production DB.

    ``allow_flag`` is the raw ``ARCHIVER_ALLOW_PRODUCTION_DB`` value. Only the
    exact string ``"1"`` opts in — a fuzzy truthiness check would let a stray
    value quietly re-open the hole this guard closes.
    """
    if is_non_production_database(url):
        return
    if allow_flag == "1":
        return

    name = database_name(url) or "<unparseable>"
    raise ProductionDatabaseRefused(
        f"refusing to start against database {name!r}: the name carries no "
        f"{' or '.join(NON_PRODUCTION_SUFFIXES)} suffix, so it is treated as "
        "production.\n"
        "  Only the systemd unit (deploy/archiver.service) may serve the "
        f"production registry; it sets {ALLOW_PRODUCTION_DB_ENV}=1.\n"
        "  For a dev server use: bash scripts/dev_server.sh\n"
        "  (See the 2026-07-18 incident note in that script.)"
    )
