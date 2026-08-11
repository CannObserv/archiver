"""Pure mapping from Watcher's WatchedItem fields onto the registry's columns.

Archiver takes ownership of scheduling policy in archiver#150, but the current
values live on Watcher's ``watched_items`` and the SDK is the only way to read
them — and archiver#142 deletes the SDK. This module decides *what* each row
should become; ``scripts/import_watch_specs.py`` owns the session, the Watcher
calls, and the transaction, per the "Caller commits" convention every other
``src/core`` helper follows.

**Two columns, from two Watcher fields.** ``default_schedule_config`` becomes the
cadence document; ``is_active`` becomes ``watch_active``. They are separate here
for the same reason they are separate in the schema: pause state is per-item and
cannot live inside a policy document that may one day be shared.
"""

from dataclasses import dataclass, field

from src.core.watch_spec_schema.validator import validate_watch_spec


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
    """Rows whose policy changed (or would change, under a dry run)."""
    unchanged: int = 0
    """Rows already holding the imported policy — the idempotent re-run case."""
    unlinked: int = 0
    """InfoItems Watcher has no WatchedItem for. Left at their existing policy."""
    failed: int = 0
    """Rows skipped — Watcher unreachable for them, or its values unusable."""
    anomalies: list[ImportAnomaly] = field(default_factory=list)


@dataclass(frozen=True)
class ItemPlan:
    """What one row should become, and what to tell the operator about it."""

    watch_spec: dict
    watch_active: bool
    changed: bool
    anomaly: str | None = None
    """Reported, but the plan still applies — e.g. a stale ``watcher_item_id``."""
    error: str | None = None
    """Reported, and the plan does **not** apply — the row is left untouched."""


def watch_spec_from_schedule_config(schedule_config: object) -> dict:
    """Build a cadence document from Watcher's ``default_schedule_config``.

    A null config means Watcher holds no per-item cadence — a real state, not a
    missing value. It maps to an **absent** ``interval``, so the consumer keeps
    applying its own default (which may be per-domain). Three of the four
    production WatchedItems are in exactly that state.

    The config arrives as the generated SDK's free-form model (or an ``UNSET``
    sentinel), not a plain dict; the model exposes ``to_dict`` and the sentinel
    does not.
    """
    config: dict = {}
    if isinstance(schedule_config, dict):
        config = schedule_config
    elif hasattr(schedule_config, "to_dict"):
        config = schedule_config.to_dict()

    doc: dict = {"schema_version": 1}
    interval = config.get("interval")
    if interval is not None:
        doc["interval"] = interval
    return doc


def plan_item_import(
    *,
    watcher_item_id: str | None,
    watch_spec: dict,
    watch_active: bool | None,
    wi_id: str,
    wi_is_active: bool,
    wi_schedule_config: object,
) -> ItemPlan:
    """Decide what one InfoItem's two policy columns should become.

    A ``watcher_item_id`` that disagrees with the WatchedItem Watcher linked is
    reported but not fatal: **Watcher's link wins**, because that column drifts
    (the 409-adoption recovery in ``watcher_provisioning`` exists because of it)
    and the join already ran from Watcher's side.

    A ``default_schedule_config`` that cannot produce a valid document *is*
    fatal for that row — a partially-written policy is worse than an unwritten
    one.
    """
    doc = watch_spec_from_schedule_config(wi_schedule_config)
    ok, errors = validate_watch_spec(doc)
    if not ok:
        return ItemPlan(
            watch_spec=watch_spec,
            watch_active=bool(watch_active),
            changed=False,
            error=(
                f"Watcher's schedule_config {wi_schedule_config!r} does not produce a "
                f"valid WatchSpec: {errors}"
            ),
        )

    anomaly = None
    if watcher_item_id and watcher_item_id != wi_id:
        anomaly = (
            f"watcher_item_id mismatch: registry has {watcher_item_id!r}, Watcher's "
            f"linked item is {wi_id!r} (Watcher's link wins)"
        )

    return ItemPlan(
        watch_spec=doc,
        watch_active=bool(wi_is_active),
        changed=(doc != watch_spec or bool(wi_is_active) != watch_active),
        anomaly=anomaly,
    )
