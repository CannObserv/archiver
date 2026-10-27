"""Temporal-profile evaluation and validation (archiver#365): pure, no database, no clock.

Watcher's semantics (``src/core/scheduling/cadence.py`` at ``127eeee``),
ported exactly, then pinned at the edges Watcher left open:

- **event and deadline share one path.** The profile applies while ``today <=
  reference_date``, the date itself included. The winning rule is the one with
  the smallest ``days_before`` still ``>=`` days-until; no covering rule means
  no interval.
- **seasonal** applies on ``start <= today <= end``, both ends inclusive, with
  its one rule's ``interval``. The dates are absolute: nothing recurs yearly.
- **The post-action is due** the day after the window: ``today > reference_date``
  or ``today > date_range_end``, whether or not any rule ever matched.
- **An inactive profile contributes nothing and fires nothing**; a fired one
  (``fired_at``) is not due again.

A profile interval **overrides** the item's base cadence rather than taking the
minimum (design C-e: profile → item → domain), so it can slow an item too.

``today`` is always a UTC calendar day (``utc_today``): every caller derives it
there, as every Watcher caller passed ``datetime.now(UTC).date()``.

Validation is stricter than Watcher's, which had none - a malformed row raised
inside its tick and stopped scheduling for every item. ``profile_errors`` is the
write-time gate, and the boundary job skips any row that fails it.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from src.core.models.temporal_profile import DATE_PROFILE_TYPES, POST_ACTIONS, PROFILE_TYPES
from src.core.watch_spec_schema.validator import validate_watch_spec

FieldErrors = list[tuple[str, str]]


@dataclass(frozen=True)
class Evaluation:
    """What a profile says on one UTC day: its interval (or none), and whether to fire."""

    interval: str | None
    post_action_due: bool


def utc_today(now: datetime) -> date:
    """The UTC calendar day of ``now``; a naive datetime is refused, not guessed."""
    if now.tzinfo is None:
        raise ValueError("now must carry a timezone")
    return now.astimezone(UTC).date()


def window_end(profile: Any) -> date:
    """The last day the profile applies: the reference date, or the range's end."""
    if profile.profile_type in DATE_PROFILE_TYPES:
        return profile.reference_date
    return profile.date_range_end


def _date_interval(profile: Any, today: date) -> str | None:
    ref = profile.reference_date
    if today > ref:
        return None
    days_until = (ref - today).days
    covering = [r for r in profile.rules if days_until <= r["days_before"]]
    if not covering:
        return None
    return min(covering, key=lambda r: r["days_before"])["interval"]


def _seasonal_interval(profile: Any, today: date) -> str | None:
    if not (profile.date_range_start <= today <= profile.date_range_end):
        return None
    return profile.rules[0]["interval"] if profile.rules else None


def evaluate(profile: Any, today: date) -> Evaluation:
    """The profile's result on ``today``. Assumes ``profile_errors(profile) == []``."""
    if not profile.is_active:
        return Evaluation(None, False)
    if profile.profile_type in DATE_PROFILE_TYPES:
        interval = _date_interval(profile, today)
    else:
        interval = _seasonal_interval(profile, today)
    due = profile.fired_at is None and today > window_end(profile)
    return Evaluation(interval, due)


_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def interval_seconds(value: str) -> int:
    """A valid interval string's length in seconds (``interval_error`` is ``None``)."""
    return int(value[:-1]) * _UNIT_SECONDS[value[-1]]


def interval_error(value: object) -> str | None:
    """Why ``value`` is not a profile interval, or ``None``.

    WatchSpec v1's grammar (``^[0-9]+[smhd]$``), and not zero: Watcher read a
    zero profile interval as no override (a falsy ``timedelta``), where Archiver
    would announce it as a concrete one.
    """
    if not isinstance(value, str):
        return "must be a string such as '6h'"
    ok, _errors = validate_watch_spec({"schema_version": 1, "interval": value})
    if not ok:
        return f"{value!r} is not an interval such as '30m', '6h' or '1d'"
    if int(value[:-1]) == 0:
        return "must be greater than zero"
    return None


def _rule_errors(rules: Sequence, *, seasonal: bool) -> FieldErrors:
    errors: FieldErrors = []
    allowed = {"interval"} if seasonal else {"days_before", "interval"}
    seen: set[int] = set()
    for i, rule in enumerate(rules):
        path = f"rules/{i}"
        if not isinstance(rule, dict):
            errors.append((path, "must be an object"))
            continue
        if seasonal and "days_before" in rule:
            errors.append((f"{path}/days_before", "a seasonal rule has no days_before"))
        extra = sorted(set(rule) - allowed - {"days_before"})
        if extra:
            errors.append((path, f"unknown keys: {', '.join(extra)}"))
        if (message := interval_error(rule.get("interval"))) is not None:
            errors.append((f"{path}/interval", message))
        if seasonal:
            continue
        days = rule.get("days_before")
        # bool is an int subclass; True is not a day count.
        if isinstance(days, bool) or not isinstance(days, int) or days < 0:
            errors.append((f"{path}/days_before", "must be an integer >= 0"))
        elif days in seen:
            errors.append((f"{path}/days_before", f"days_before {days} appears twice"))
        else:
            seen.add(days)
    return errors


def profile_errors(profile: Any) -> FieldErrors:
    """Every reason ``profile`` cannot be stored or evaluated, as ``(path, message)``.

    Shape only: whether its window has already ended depends on the day, so the
    write path checks that separately.
    """
    errors: FieldErrors = []
    ptype = profile.profile_type
    if ptype not in PROFILE_TYPES:
        errors.append(("profile_type", f"must be one of {', '.join(PROFILE_TYPES)}"))
    if profile.post_action not in POST_ACTIONS:
        errors.append(("post_action", f"must be one of {', '.join(POST_ACTIONS)}"))
    if ptype in DATE_PROFILE_TYPES:
        if profile.reference_date is None:
            errors.append(("reference_date", f"required for {ptype}"))
        for field in ("date_range_start", "date_range_end"):
            if getattr(profile, field) is not None:
                errors.append((field, f"not allowed for {ptype}"))
    elif ptype == "seasonal":
        if profile.reference_date is not None:
            errors.append(("reference_date", "not allowed for seasonal"))
        start, end = profile.date_range_start, profile.date_range_end
        for field, value in (("date_range_start", start), ("date_range_end", end)):
            if value is None:
                errors.append((field, "required for seasonal"))
        if start is not None and end is not None and start > end:
            errors.append(("date_range_end", "must not be before date_range_start"))
    rules = profile.rules
    if not isinstance(rules, list):
        errors.append(("rules", "must be a list"))
        return errors
    seasonal = ptype == "seasonal"
    if seasonal and len(rules) != 1:
        errors.append(("rules", "seasonal takes exactly one rule"))
    errors.extend(_rule_errors(rules, seasonal=seasonal))
    return errors
