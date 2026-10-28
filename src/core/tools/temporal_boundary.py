"""The daily temporal-profile boundary (archiver#365): one evaluation of every profile.

``deploy/archiver-temporal-boundary.timer`` runs ``main`` at 00:05 UTC, with
``Persistent=true``, so a boundary missed while the host was down runs when it
returns. Each profile is recomputed for the UTC day; an item whose result moved,
or whose post-action fired, announces once on ``info.registry`` through the
outbox, and the resident publisher drains it (no Redis here). Idempotent: the
stored result is the comparison, so a second run the same day emits nothing
(``src.core.services.temporal_profiles``).

``--today YYYY-MM-DD`` evaluates another day, for stepping a profile across
dates on the dev server (archiver_dev). Against any database not named
``_test``/``_dev`` it must be today's UTC date, or the run exits 2 without
writing: another day would announce intervals early or late and fire
post-actions that are not due.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import UTC, date, datetime

from src.core.database import get_database_url, get_engine, get_session_factory
from src.core.db_safety import (
    ALLOW_PRODUCTION_DB_ENV,
    assert_production_db_allowed,
    is_non_production_database,
)
from src.core.logging import configure_logging, get_logger
from src.core.services.temporal_evaluation import utc_today
from src.core.services.temporal_profiles import run_boundary

# Literal rather than __name__: the timer runs this module via ``python -m``,
# where __name__ is "__main__" - a useless journald filter key.
logger = get_logger("src.core.tools.temporal_boundary")

EXIT_OK = 0
EXIT_REFUSED = 2


def _now() -> datetime:
    return datetime.now(UTC)


def main(argv: list[str] | None = None) -> int:
    """Timer entrypoint: evaluate every profile for the UTC day, exit 0.

    A malformed profile is a WARNING and the rest still run; only a crash here
    exits non-zero (or a refused ``--today``, 2).
    """
    parser = argparse.ArgumentParser(description="archiver temporal-profile boundary")
    parser.add_argument(
        "--today",
        type=date.fromisoformat,
        help="the UTC day to evaluate (YYYY-MM-DD); only today's against production",
    )
    args = parser.parse_args(argv)

    configure_logging()
    database_url = get_database_url()
    assert_production_db_allowed(database_url, allow_flag=os.environ.get(ALLOW_PRODUCTION_DB_ENV))
    actual = utc_today(_now())
    today = args.today or actual
    if today != actual and not is_non_production_database(database_url):
        logger.error(
            "--today must be today's UTC date against production; nothing evaluated",
            extra={"today": today.isoformat(), "utc_today": actual.isoformat()},
        )
        return EXIT_REFUSED

    async def _run() -> None:
        try:
            async with get_session_factory()() as db:
                await run_boundary(db, today=today)
        finally:
            await get_engine().dispose()

    asyncio.run(_run())
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
