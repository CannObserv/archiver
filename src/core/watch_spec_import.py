"""One-time import of Watcher-owned cadence + active state onto ``watch_spec``.

Archiver takes ownership of scheduling policy in archiver#150, but the current
values live on Watcher's ``watched_items`` and the SDK is the only way to read
them — and archiver#142 deletes the SDK. This module moves them across.

Written to be **re-runnable**, not a one-shot: it lands with the migration and
is run again immediately before the announcement producer's first publish.
Watcher stays authoritative in between, so a snapshot taken once at the start
would be stale by the time it is announced as desired state.

The join runs from **Watcher's** ``archiver_info_item_id`` (via
``get_by_info_item_id``), never from Archiver's ``watcher_item_id``: that column
drifts — the 409-adoption recovery in ``watcher_provisioning`` exists because of
it — and a stale value would silently drop a row from the import.
"""

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from watcher_client import WatcherClient

from src.core.logging import get_logger
from src.core.models import InfoItem
from src.core.watch_spec_schema.validator import validate_watch_spec

logger = get_logger(__name__)


@dataclass(frozen=True)
class ImportAnomaly:
    """Something the operator has to look at before trusting the run."""

    info_item_id: str
    reason: str


@dataclass
class ImportReport:
    """Outcome of one import pass."""

    dry_run: bool = False
    imported: int = 0
    """Rows whose watch_spec changed (or would change, under --dry-run)."""
    unchanged: int = 0
    """Rows already holding the imported policy — the idempotent re-run case."""
    unlinked: int = 0
    """InfoItems Watcher has no WatchedItem for. Left at their existing policy."""
    anomalies: list[ImportAnomaly] = field(default_factory=list)


def watch_spec_from_watched_item(is_active: bool, schedule_config: object) -> dict:
    """Build a WatchSpec document from Watcher's two fields.

    A null ``default_schedule_config`` means Watcher holds no per-item cadence —
    a real state, not a missing value. It maps to an **absent** ``interval``, so
    the consumer keeps applying its own default (which may be per-domain).

    ``schedule_config`` arrives as the generated SDK's free-form model (or an
    ``UNSET`` sentinel), not a plain dict; both expose ``to_dict``.
    """
    config: dict = {}
    if isinstance(schedule_config, dict):
        config = schedule_config
    elif hasattr(schedule_config, "to_dict"):
        config = schedule_config.to_dict()

    doc: dict = {"schema_version": 1, "active": bool(is_active)}
    interval = config.get("interval")
    if interval is not None:
        doc["interval"] = interval
    return doc


async def import_watch_specs(
    session: AsyncSession,
    watcher: WatcherClient,
    *,
    dry_run: bool = False,
) -> ImportReport:
    """Copy every WatchedItem's cadence + active state onto its InfoItem.

    Never partially writes a row: a document that fails validation is reported
    and skipped, leaving the existing policy in place.
    """
    report = ImportReport(dry_run=dry_run)
    items = list((await session.execute(select(InfoItem))).scalars().all())

    for item in items:
        item_id = str(item.info_item_id)
        wi = await watcher.get_by_info_item_id(item_id)
        if wi is None:
            report.unlinked += 1
            continue

        if item.watcher_item_id and item.watcher_item_id != str(wi.id):
            report.anomalies.append(
                ImportAnomaly(
                    item_id,
                    f"watcher_item_id mismatch: registry has {item.watcher_item_id!r}, "
                    f"Watcher's linked item is {str(wi.id)!r} (Watcher's link wins)",
                )
            )

        doc = watch_spec_from_watched_item(wi.is_active, wi.default_schedule_config)
        ok, errors = validate_watch_spec(doc)
        if not ok:
            report.anomalies.append(
                ImportAnomaly(
                    item_id,
                    f"Watcher's schedule_config {wi.default_schedule_config!r} does not "
                    f"produce a valid WatchSpec: {errors}",
                )
            )
            continue

        if item.watch_spec == doc:
            report.unchanged += 1
            continue

        report.imported += 1
        if not dry_run:
            item.watch_spec = doc

    if dry_run:
        return report

    await session.flush()
    await session.commit()
    logger.info(
        "watch_spec import complete",
        extra={
            "imported": report.imported,
            "unchanged": report.unchanged,
            "unlinked": report.unlinked,
            "anomalies": len(report.anomalies),
        },
    )
    return report
