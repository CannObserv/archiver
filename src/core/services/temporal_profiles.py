"""Temporal-profile writes and the daily boundary (archiver#365, design D5/D7).

Archiver executes an InfoItem's temporal profile and announces only the result:
the resolved interval and ``active`` (placement rule 4). Two paths compute a
profile's result, and nothing else does (the coordinator brief's D1):

- **a profile write** (``put_temporal_profile``, ``delete_temporal_profile``):
  the API and the dashboard;
- **the boundary job** (``evaluate_at_boundary`` per item, ``run_boundary``
  over all of them), run daily by ``src.core.tools.temporal_boundary``.

Each stores the result on the profile row (``resolved_interval`` for the UTC
day ``evaluated_on``) and announces in the same transaction **only when it
moved**, so a same-day rerun emits nothing. The announce path reads the stored
value and never the clock, so the hourly snapshot replays the last delta.

**Post-actions fire at the boundary** the day after the window, whatever the
item's pause, archive or host state (D4): Archiver owns the intent and keeps its
own clock, where Watcher's tick fired late, on resume. ``fired_at`` makes them
one-shot; ``is_active`` stays the operator's switch, and an inactive profile
neither contributes nor fires.

- ``deactivate``: ``watch_active = false``.
- ``archive``: ``info_item_lifecycle.archive_info_item`` (archiver#361).
- ``reduce_frequency``: the item's own ``interval = "1d"``, only when its base
  (item, then domain; profile excluded) is faster than 1d (D3). A slower item is
  not sped up (watcher#205), and no base means Watcher's own 1d default.

On the boundary day an event profile stops contributing and fires together, in
one transaction, and the item announces **once**, with the final state.

**Re-arm** (the brief's open question): every accepted write clears
``fired_at``. A write whose window has already ended is refused, so a re-armed
profile can never fire a second time on dates that have passed.

**Lock order: the item, then its host's Domain row**, the order every announce
takes. Both paths lock the item ``FOR UPDATE`` before reading the profile, so a
write and the job serialize and the second sees the first. The caller commits,
except ``run_boundary``, which commits per item so that one bad row cannot roll
back the rest.
"""

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.core.logging import get_logger
from src.core.models import Domain, InfoItem, InfoItemSource, InfoSource, TemporalProfile
from src.core.services import info_item_lifecycle
from src.core.services.cadence_resolution import resolve_interval
from src.core.services.registry_announcement import announce_policy_change, is_announceable
from src.core.services.temporal_evaluation import (
    FieldErrors,
    evaluate,
    interval_seconds,
    profile_errors,
    window_end,
)

logger = get_logger(__name__)

WRITABLE_FIELDS = (
    "profile_type",
    "reference_date",
    "date_range_start",
    "date_range_end",
    "rules",
    "post_action",
    "is_active",
)
REDUCED_INTERVAL = "1d"


class ProfileInvalid(ValueError):
    """The profile cannot be stored; ``errors`` is ``[(path, message)]``."""

    def __init__(self, errors: FieldErrors):
        super().__init__("; ".join(f"{path}: {message}" for path, message in errors))
        self.errors = errors


async def _lock_item(session: AsyncSession, info_item_id: ULID | str) -> InfoItem | None:
    return (
        await session.execute(
            select(InfoItem)
            .where(InfoItem.info_item_id == info_item_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


async def _profile(session: AsyncSession, info_item_id: ULID) -> TemporalProfile | None:
    """The item's profile, fresh: read only under the item lock."""
    return (
        await session.execute(
            select(TemporalProfile)
            .where(TemporalProfile.info_item_id == info_item_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


def _write_errors(candidate: TemporalProfile, today: date) -> FieldErrors:
    errors = profile_errors(candidate)
    if errors:
        return errors
    if window_end(candidate) < today:
        field = "date_range_end" if candidate.profile_type == "seasonal" else "reference_date"
        errors.append((field, f"the window ended before today ({today.isoformat()}, UTC)"))
    return errors


async def put_temporal_profile(
    session: AsyncSession, info_item_id: ULID | str, fields: Mapping[str, Any], *, today: date
) -> TemporalProfile | None:
    """Create or replace the item's profile; ``None`` when the item is missing.

    ``fields`` holds every name in ``WRITABLE_FIELDS``: a whole-document
    replace. Raises ``ProfileInvalid`` before writing anything. Evaluates for
    ``today`` (a UTC day), clears ``fired_at`` (re-arm), and announces when the
    stored result moved. The caller commits.
    """
    unknown = set(fields) - set(WRITABLE_FIELDS)
    if unknown:
        raise ValueError(f"not writable on a TemporalProfile: {sorted(unknown)}")
    missing = set(WRITABLE_FIELDS) - set(fields)
    if missing:
        raise ValueError(f"a TemporalProfile write needs every field; missing {sorted(missing)}")
    candidate = TemporalProfile(**{name: fields[name] for name in WRITABLE_FIELDS})
    errors = _write_errors(candidate, today)
    if errors:
        raise ProfileInvalid(errors)

    item = await _lock_item(session, info_item_id)
    if item is None:
        return None
    profile = await _profile(session, item.info_item_id)
    before = profile.resolved_interval if profile is not None else None
    if profile is None:
        profile = TemporalProfile(info_item_id=item.info_item_id)
        session.add(profile)
    for name in WRITABLE_FIELDS:
        setattr(profile, name, getattr(candidate, name))
    profile.fired_at = None
    profile.resolved_interval = evaluate(profile, today).interval
    profile.evaluated_on = today
    await session.flush()
    if profile.resolved_interval != before:
        await announce_policy_change(session, item.info_item_id)
    return profile


async def delete_temporal_profile(session: AsyncSession, info_item_id: ULID | str) -> bool:
    """Delete the item's profile; ``False`` when it has none (or the item is missing).

    Announces when the profile held a result, so the tier below takes over on
    the wire. The caller commits.
    """
    item = await _lock_item(session, info_item_id)
    if item is None:
        return False
    profile = await _profile(session, item.info_item_id)
    if profile is None:
        return False
    held = profile.resolved_interval
    await session.delete(profile)
    await session.flush()
    if held is not None:
        await announce_policy_change(session, item.info_item_id)
    return True


@dataclass(frozen=True)
class BoundaryOutcome:
    """What one item's boundary evaluation did."""

    moved: bool = False
    fired: str | None = None
    announced: bool = False
    skipped: bool = False


async def _host(session: AsyncSession, info_item_id: ULID) -> Domain | None:
    """The announcing host's Domain row, ``FOR KEY SHARE`` as an announce reads it."""
    return (
        await session.execute(
            select(Domain)
            .join(InfoSource, InfoSource.domain_name == Domain.name)
            .join(InfoItemSource, InfoItemSource.info_source_id == InfoSource.info_source_id)
            .where(
                InfoItemSource.info_item_id == info_item_id,
                InfoItemSource.deactivated_at.is_(None),
            )
            .with_for_update(read=True, key_share=True, of=Domain)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


async def _reduce_frequency(session: AsyncSession, item: InfoItem) -> bool:
    """Write the item's own 1d interval if its base is faster; returns whether it wrote."""
    base = resolve_interval(
        profile=None, item=item, domain=await _host(session, item.info_item_id)
    ).interval
    # No base is Watcher's own 1d default: nothing to slow (watcher#205).
    if base is None or interval_seconds(base) >= interval_seconds(REDUCED_INTERVAL):
        return False
    item.watch_spec = {"schema_version": 1, "interval": REDUCED_INTERVAL}
    return True


async def evaluate_at_boundary(
    session: AsyncSession, info_item_id: ULID | str, *, today: date
) -> BoundaryOutcome:
    """Recompute one item's profile for ``today`` and fire a due post-action.

    Announces once, with the final state, when the stored result moved or the
    post-action changed the item; an archive that transitions announces itself
    (``archive_info_item``), after every other write here is flushed. A row
    that fails validation is skipped with a WARNING. The caller commits.
    """
    item = await _lock_item(session, info_item_id)
    profile = await _profile(session, item.info_item_id) if item is not None else None
    if profile is None:
        return BoundaryOutcome()
    errors = profile_errors(profile)
    if errors:
        logger.warning(
            "TemporalProfile is malformed; skipped at the boundary",
            extra={"info_item_id": str(item.info_item_id), "errors": errors},
        )
        return BoundaryOutcome(skipped=True)

    result = evaluate(profile, today)
    moved = result.interval != profile.resolved_interval
    profile.resolved_interval = result.interval
    profile.evaluated_on = today
    fired = profile.post_action if result.post_action_due else None
    changed = False
    archiving = False
    if fired is not None:
        profile.fired_at = datetime.now(UTC)
        if fired == "deactivate":
            changed = item.watch_active is not False
            item.watch_active = False
        elif fired == "reduce_frequency":
            changed = await _reduce_frequency(session, item)
        elif fired == "archive":
            archiving = item.archived_at is None
        logger.info(
            "TemporalProfile post-action fired",
            extra={
                "info_item_id": str(item.info_item_id),
                "post_action": fired,
                "changed": changed or archiving,
            },
        )
    await session.flush()

    announced = False
    if archiving:
        # Its own announce carries the final state: everything above is flushed.
        await info_item_lifecycle.archive_info_item(session, item.info_item_id)
        announced = await is_announceable(session, item.info_item_id)
    elif moved or changed:
        announced = await announce_policy_change(session, item.info_item_id)
    return BoundaryOutcome(moved=moved, fired=fired, announced=announced)


async def run_boundary(session: AsyncSession, *, today: date) -> dict[str, int]:
    """Evaluate every profile for ``today``, one committed transaction per item.

    Returns the counts it logs: evaluated, moved, fired, announced, skipped. An
    unexpected error on one item rolls that item back, is logged, and counts as
    skipped; the rest still run.
    """
    item_ids = list(
        (
            await session.execute(
                select(TemporalProfile.info_item_id).order_by(TemporalProfile.info_item_id)
            )
        ).scalars()
    )
    await session.commit()
    counts: Counter[str] = Counter(evaluated=0, moved=0, fired=0, announced=0, skipped=0)
    for info_item_id in item_ids:
        try:
            outcome = await evaluate_at_boundary(session, info_item_id, today=today)
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception(
                "TemporalProfile boundary evaluation failed; rolled back",
                extra={"info_item_id": str(info_item_id)},
            )
            outcome = BoundaryOutcome(skipped=True)
        counts["evaluated"] += 1
        counts["moved"] += outcome.moved
        counts["fired"] += outcome.fired is not None
        counts["announced"] += outcome.announced
        counts["skipped"] += outcome.skipped
    logger.info(
        "temporal boundary finished",
        extra={"today": today.isoformat(), **counts},
    )
    return dict(counts)
