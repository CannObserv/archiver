"""The Notifications page's content options: form parsing and the view (archiver#363). Pure.

One fieldset per block - ``default`` and each event's override - with field
names ``<block>__<option>``; ``override__<event>`` turns that event's block on.
Checkboxes post only when ticked, so the form renders every toggle and an
unticked one is ``False``.

**What is stored is the difference from the defaults** (``exclude_defaults``),
so the default form stores ``None`` and a later default change (#367) still
applies to rows that never chose otherwise. An override replaces the defaults
for its event, as in Watcher: an enabled override at defaults stores ``{}``.

**The Jinja fields stay API-only until #367's preview** (D5). The form never
shows them, so it carries the stored ones over, and refuses to turn off an
override that holds one rather than erase it.
"""

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from src.core.models.notification_subscription import NOTIFICATION_EVENTS
from src.core.notifications.content_config import ContentConfig, ContentOptions

EVENT_LABELS = {
    "change_detected": "Change",
    "watch_error": "Error",
    "watch_recovered": "Recovered",
}
"""Watcher's ``EVENT_TITLES``, in declaration order."""


def event_labels(events: list[str]) -> str:
    """``events`` as their labels, in declaration order: ``"Change, Error"``."""
    return ", ".join(EVENT_LABELS[e] for e in NOTIFICATION_EVENTS if e in events)


TOGGLES = (
    ("include_diff_snippet", "Diff snippet"),
    ("include_diff_full", "Full diff"),
    ("include_temporal_context", "Check interval"),
    ("include_domain", "Domain"),
    ("include_last_changed_at", "Last changed"),
    ("include_description", "Description"),
    ("include_tags", "Tags (none exist yet)"),
)
TEMPLATE_FIELDS = ("title_template", "body_template")


def options_view(config: dict | None) -> dict[str, Any]:
    """Every option filled in, for the form: ``default``, ``overrides`` (``None``
    where an event has none) and ``templates``, whether any Jinja field is set."""
    parsed = ContentConfig.model_validate(config or {})
    overrides = {e: parsed.overrides.get(e) for e in NOTIFICATION_EVENTS}
    blocks = [parsed.default, *(o for o in overrides.values() if o is not None)]
    return {
        "default": parsed.default.model_dump(),
        "overrides": {e: (o.model_dump() if o else None) for e, o in overrides.items()},
        "templates": any(getattr(b, f) for b in blocks for f in TEMPLATE_FIELDS),
    }


def _block(form: Mapping[str, Any], prefix: str, problems: list[str]) -> dict[str, Any]:
    block: dict[str, Any] = {name: bool(form.get(f"{prefix}__{name}")) for name, _ in TOGGLES}
    raw = str(form.get(f"{prefix}__diff_snippet_lines") or "").strip()
    if raw.isdigit() and 1 <= int(raw) <= 200:
        block["diff_snippet_lines"] = int(raw)
    else:
        label = "Default" if prefix == "default" else EVENT_LABELS[prefix]
        problems.append(f"{label}: diff snippet lines must be a whole number, 1-200")
    return block


def _templates_of(options: Mapping[str, Any] | None) -> dict[str, str]:
    return {f: options[f] for f in TEMPLATE_FIELDS if options and options.get(f)}


def content_config_from_form(
    form: Mapping[str, Any], stored: dict | None
) -> tuple[dict | None, list[str]]:
    """The ``content_config`` to store, and what would not parse.

    ``stored`` is the row's current config, whose Jinja fields carry over.
    """
    problems: list[str] = []
    stored = stored or {}
    stored_overrides = stored.get("overrides") or {}
    default = _block(form, "default", problems) | _templates_of(stored.get("default"))
    overrides: dict[str, dict] = {}
    for event in NOTIFICATION_EVENTS:
        kept = _templates_of(stored_overrides.get(event))
        if form.get(f"override__{event}"):
            overrides[event] = _block(form, event, problems) | kept
        elif kept:
            problems.append(
                f"the {EVENT_LABELS[event]} override holds a Jinja template set through "
                "the API; change or remove it through the API"
            )
    if problems:
        return None, problems
    try:
        config = ContentConfig(default=ContentOptions(**default), overrides=overrides)
    except ValidationError as e:  # only a stored template can fail here
        return None, [err["msg"] for err in e.errors()]
    dumped = config.model_dump(exclude_defaults=True)
    if config.overrides:
        dumped["overrides"] = {
            e: o.model_dump(exclude_defaults=True) for e, o in config.overrides.items()
        }
    return (dumped or None), []
