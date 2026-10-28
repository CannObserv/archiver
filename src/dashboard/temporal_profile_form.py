"""The watch panel's Temporal profile row (archiver#365): form parsing and the readout. Pure.

The form posts one text field for the rules, so the row stays one row:
``30:6h, 7:1h`` (``days_before:interval``) for event and deadline, a bare
``2h`` for seasonal. Parsing here only turns text into the service's fields;
every rule the profile must meet is ``temporal_evaluation.profile_errors``'s,
applied by the service the API uses too.
"""

from datetime import date
from typing import Any

from src.core.models.temporal_profile import DATE_PROFILE_TYPES, TemporalProfile
from src.dashboard.watch_panel import format_interval

_DATE_FIELDS = ("reference_date", "date_range_start", "date_range_end")
_OWN_DATES = {
    "event": ("reference_date",),
    "deadline": ("reference_date",),
    "seasonal": ("date_range_start", "date_range_end"),
}


def _rules(text: str, *, seasonal: bool, problems: list[str]) -> list[dict]:
    rules: list[dict] = []
    for part in (p.strip() for p in text.split(",")):
        if not part:
            continue
        if seasonal:
            rules.append({"interval": part})
            continue
        days, sep, interval = part.partition(":")
        if not sep or not days.strip().isdigit():
            problems.append(f"rule {part!r}: write it as days_before:interval, e.g. 7:1h")
            continue
        rules.append({"days_before": int(days.strip()), "interval": interval.strip()})
    return rules


def fields_from_form(form: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """The service's fields from the posted form, and anything that would not parse.

    Only the type's own date inputs are read: the form posts all three, and a
    stale value in a hidden one must not reach the service as a refusal.
    """
    problems: list[str] = []
    ptype = (form.get("profile_type") or "").strip()
    fields: dict[str, Any] = {name: None for name in _DATE_FIELDS}
    for name in _OWN_DATES.get(ptype, ()):
        raw = (form.get(name) or "").strip()
        if not raw:
            continue
        try:
            fields[name] = date.fromisoformat(raw)
        except ValueError:
            problems.append(f"{name}: {raw!r} is not a date (YYYY-MM-DD)")
    fields["profile_type"] = ptype
    fields["rules"] = _rules(
        form.get("rules") or "", seasonal=ptype == "seasonal", problems=problems
    )
    fields["post_action"] = (form.get("post_action") or "").strip()
    fields["is_active"] = form.get("is_active") == "on"
    return fields, problems


def _label(interval: object) -> str:
    return format_interval(interval) or str(interval)


def _rules_text(profile: TemporalProfile) -> str:
    if profile.profile_type == "seasonal":
        return ", ".join(str(r.get("interval", "")) for r in profile.rules if isinstance(r, dict))
    return ", ".join(
        f"{r.get('days_before')}:{r.get('interval')}" for r in profile.rules if isinstance(r, dict)
    )


def _summary(profile: TemporalProfile) -> str:
    then = f"then {profile.post_action.replace('_', ' ')}"
    rules = [r for r in profile.rules if isinstance(r, dict)]
    if profile.profile_type in DATE_PROFILE_TYPES:
        steps = ", ".join(
            f"{r.get('days_before')} days out {_label(r.get('interval'))}" for r in rules
        )
        head = f"{profile.profile_type.capitalize()} on {profile.reference_date}"
        return f"{head}: {steps or 'no rules'}; {then}"
    interval = _label(rules[0].get("interval")) if rules else "no rule"
    return f"Seasonal {profile.date_range_start} to {profile.date_range_end}: {interval}; {then}"


def _status(profile: TemporalProfile) -> str:
    evaluated = f"(evaluated {profile.evaluated_on})"
    if not profile.is_active:
        status = f"Off {evaluated}"
    elif profile.resolved_interval is not None:
        status = f"Now {_label(profile.resolved_interval)} {evaluated}"
    else:
        status = f"Not setting the cadence {evaluated}"
    if profile.fired_at is not None:
        status += f"; fired {profile.fired_at.date()}"
    return status


def profile_view(profile: TemporalProfile | None) -> dict[str, Any] | None:
    """What the row renders: a summary, the result's status, and the form's values."""
    if profile is None:
        return None
    return {
        "summary": _summary(profile),
        "status": _status(profile),
        "rules_text": _rules_text(profile),
        "form": {
            "profile_type": profile.profile_type,
            "post_action": profile.post_action,
            "is_active": profile.is_active,
            **{
                name: getattr(profile, name).isoformat() if getattr(profile, name) else ""
                for name in _DATE_FIELDS
            },
        },
    }
