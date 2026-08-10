"""One-time import of Watcher's cadence + active state onto ``info_items.watch_spec``.

Archiver#150 moves scheduling policy into the registry, but the live values are
Watcher's and the SDK is the only reader — archiver#142 deletes it. This is the
step's single irreversible action.

**Run it twice.** Once when the migration lands, and again immediately before
the announcement producer's first publish (archiver#141): Watcher stays
authoritative in between, so a snapshot taken only at the start would be
announced stale. The pass is idempotent, so the second run is free.

Dry run is the default; ``--apply`` is required to write. Exits non-zero when
the pass reported anomalies, so a clean exit means a clean run.

    set -a; . /etc/archiver/.env; [ -f .env ] && . .env; set +a
    uv run python -m scripts.import_watch_specs            # report only
    uv run python -m scripts.import_watch_specs --apply    # write

Exit codes:
  0  clean — no anomalies
  1  completed, but anomalies were reported (read them before trusting the run)
  2  could not run (Watcher not configured, DB unreachable)
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from contextlib import asynccontextmanager

from watcher_client import WatcherClient

from src.core.database import get_session_factory
from src.core.logging import configure_logging
from src.core.watch_spec_import import ImportReport, import_watch_specs


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments. Writing is opt-in, never the default."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--apply",
        dest="dry_run",
        action="store_false",
        default=True,
        help="Write the imported policies. Without it the run only reports.",
    )
    return parser.parse_args(argv)


def format_report(report: ImportReport) -> str:
    """Render a report an operator can check against the live WatchedItems."""
    header = "DRY RUN — nothing written" if report.dry_run else "APPLIED"
    lines = [
        f"watch_spec import: {header}",
        f"  imported:  {report.imported}",
        f"  unchanged: {report.unchanged}",
        f"  unlinked:  {report.unlinked}  (no WatchedItem in Watcher; policy left alone)",
    ]
    if report.anomalies:
        lines.append(f"  ANOMALIES: {len(report.anomalies)}")
        lines.extend(f"    - {a.info_item_id}: {a.reason}" for a in report.anomalies)
    return "\n".join(lines)


async def _build_watcher() -> WatcherClient | None:
    base_url = os.environ.get("WATCHER_BASE_URL", "").strip()
    api_key = os.environ.get("WATCHER_API_KEY", "").strip()
    if not base_url or not api_key:
        return None
    return WatcherClient(base_url=base_url, api_key=api_key)


@asynccontextmanager
async def _session_scope():
    factory = get_session_factory()
    async with factory() as session:
        yield session


async def run(*, dry_run: bool) -> int:
    """Run one import pass. Returns the process exit code."""
    watcher = await _build_watcher()
    if watcher is None:
        print(
            "WATCHER_BASE_URL / WATCHER_API_KEY are not set — nothing to import from.",
            file=sys.stderr,
        )
        return 2

    async with _session_scope() as session:
        report = await import_watch_specs(session, watcher, dry_run=dry_run)

    print(format_report(report))
    return 1 if report.anomalies else 0


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = parse_args(argv)
    return asyncio.run(run(dry_run=args.dry_run))


if __name__ == "__main__":
    raise SystemExit(main())
