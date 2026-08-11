"""One-time import of Watcher's cadence + active state onto the registry.

Archiver#150 moves scheduling policy into the registry — ``info_items.watch_spec``
(cadence) and ``info_items.watch_active`` (pause state) — but the live values are
Watcher's and the SDK is the only reader; archiver#142 deletes it. This is the
step's single irreversible action.

**Run it twice.** Once when the migration lands, and again immediately before the
announcement producer's first publish (archiver#141): Watcher stays authoritative
in between, so a snapshot taken only at the start would be announced stale. The
pass is idempotent, so the second run is free.

Dry run is the default; ``--apply`` is required to write. Exits non-zero when the
pass reported anomalies, so a clean exit means a clean run.

    set -a; . /etc/archiver/.env; [ -f .env ] && . .env; set +a
    uv run python -m scripts.import_watch_specs            # report only
    uv run python -m scripts.import_watch_specs --apply    # write

Exit codes:
  0  clean — no anomalies
  1  completed, but anomalies were reported (read them before trusting the run)
  2  could not run (Watcher not configured, DB unreachable)

**Cost model.** One row set held in memory and one Watcher call per InfoItem —
bounded by the registry size at run time, which is four rows today and is
expected to stay operator-scale through the cutover. If that stops being true,
page the query and batch the lookups; do not assume today's number.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from contextlib import asynccontextmanager

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from watcher_client import WatcherClient

from src.core.database import get_session_factory
from src.core.logging import configure_logging, get_logger
from src.core.models import InfoItem
from src.core.watch_spec_import import (
    ImportAnomaly,
    ImportReport,
    MappingRow,
    plan_item_import,
)

logger = get_logger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments. Writing is opt-in, never the default."""
    parser = argparse.ArgumentParser(description="Import Watcher's cadence + active state.")
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
        f"watch policy import: {header}",
        f"  imported:  {report.imported}",
        f"  unchanged: {report.unchanged}",
        f"  unlinked:  {report.unlinked}  (no WatchedItem in Watcher; policy left alone)",
        f"  failed:    {report.failed}  (skipped; row left untouched)",
    ]
    if report.dry_run and report.mapping:
        lines.append("")
        lines.append(f"  {'info_item_id':<28} {'watched_item':<28} {'disposition':<12} policy")
        for row in report.mapping:
            spec = "-"
            if row.watch_spec is not None:
                spec = str(row.watch_spec.get("interval", "(consumer default)"))
            active = "-"
            if row.watch_active is not None:
                active = "active" if row.watch_active else "paused"
            lines.append(
                f"  {row.info_item_id:<28} {row.wi_id or '-':<28} "
                f"{row.disposition:<12} {spec} / {active}"
            )
    if report.anomalies:
        lines.append("")
        lines.append(f"  ANOMALIES: {len(report.anomalies)}")
        lines.extend(f"    - {a.info_item_id}: {a.reason}" for a in report.anomalies)
    return "\n".join(lines)


async def import_watch_specs(
    session: AsyncSession,
    watcher: WatcherClient,
    *,
    dry_run: bool = False,
) -> ImportReport:
    """Copy every WatchedItem's cadence + active state onto its InfoItem.

    The join runs from **Watcher's** ``archiver_info_item_id`` (via
    ``get_by_info_item_id``), never from Archiver's ``watcher_item_id``: that
    column drifts, and a stale value would silently drop a row from the import.

    **Commits per row, and isolates both halves.** A failed lookup *and* a failed
    write are each reported and skipped without discarding the rows already
    imported — the pass is re-runnable, so partial progress is strictly better
    than none. An unmatched item is an anomaly, not a quiet skip.
    """
    report = ImportReport(dry_run=dry_run)
    # Plain rows, not ORM objects: a rollback mid-pass expires every instance in
    # the identity map, and the next attribute read would then attempt implicit
    # IO from sync context (MissingGreenlet). Snapshotting up front also keeps
    # the write a single UPDATE per row.
    rows = (
        await session.execute(
            select(
                InfoItem.info_item_id,
                InfoItem.watcher_item_id,
                InfoItem.watch_spec,
                InfoItem.watch_active,
            )
        )
    ).all()

    for info_item_id, watcher_item_id, watch_spec, watch_active in rows:
        item_id = str(info_item_id)
        try:
            wi = await watcher.get_by_info_item_id(item_id)
        except Exception as e:  # noqa: BLE001 — one bad row must not end the pass
            report.failed += 1
            report.anomalies.append(ImportAnomaly(item_id, f"Watcher lookup failed: {e!r}"))
            report.mapping.append(MappingRow(item_id, None, "failed", None, None))
            logger.exception("watch policy import: Watcher lookup failed", extra={"item": item_id})
            continue

        if wi is None:
            # An unmatched row is a finding, not a quiet skip: the acceptance
            # criterion is that every registered item is linked.
            report.unlinked += 1
            report.anomalies.append(
                ImportAnomaly(item_id, "no WatchedItem in Watcher for this InfoItem")
            )
            report.mapping.append(MappingRow(item_id, None, "unlinked", None, None))
            continue

        plan = plan_item_import(
            watcher_item_id=watcher_item_id,
            watch_spec=watch_spec,
            watch_active=watch_active,
            wi_id=str(wi.id),
            wi_is_active=wi.is_active,
            wi_schedule_config=wi.default_schedule_config,
        )
        if plan.anomaly:
            report.anomalies.append(ImportAnomaly(item_id, plan.anomaly))
        if plan.error:
            report.failed += 1
            report.anomalies.append(ImportAnomaly(item_id, plan.error))
            report.mapping.append(MappingRow(item_id, str(wi.id), "failed", None, None))
            continue

        row = MappingRow(
            item_id,
            str(wi.id),
            "imported" if plan.changed else "unchanged",
            plan.watch_spec,
            plan.watch_active,
        )
        if not plan.changed:
            report.unchanged += 1
            report.mapping.append(row)
            continue

        if dry_run:
            report.imported += 1
            report.mapping.append(row)
            continue

        try:
            await session.execute(
                update(InfoItem)
                .where(InfoItem.info_item_id == info_item_id)
                .values(watch_spec=plan.watch_spec, watch_active=plan.watch_active)
            )
            await session.commit()
        except Exception as e:  # noqa: BLE001 — a failed write is one row, not the pass
            await session.rollback()
            report.failed += 1
            report.anomalies.append(ImportAnomaly(item_id, f"write failed: {e!r}"))
            report.mapping.append(MappingRow(item_id, str(wi.id), "failed", None, None))
            logger.exception("watch policy import: write failed", extra={"item": item_id})
            continue

        report.imported += 1
        report.mapping.append(row)

    logger.info(
        "watch policy import complete",
        extra={
            "dry_run": dry_run,
            "imported": report.imported,
            "unchanged": report.unchanged,
            "unlinked": report.unlinked,
            "failed": report.failed,
            "anomalies": len(report.anomalies),
        },
    )
    return report


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

    try:
        async with _session_scope() as session:
            report = await import_watch_specs(session, watcher, dry_run=dry_run)
    finally:
        await watcher.aclose()

    print(format_report(report))
    return 1 if report.anomalies else 0


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = parse_args(argv)
    return asyncio.run(run(dry_run=args.dry_run))


if __name__ == "__main__":
    raise SystemExit(main())
