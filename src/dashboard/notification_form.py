"""The Notifications page's content options: form parsing, the view and the preview
(archiver#363 D5, #367 D5). Pure.

One fieldset per block (``default`` and each event's override), with field
names ``<block>__<option>``; ``override__<event>`` turns that event's block on.
Checkboxes post only when ticked, so the form renders every toggle and an
unticked one is ``False``.

**What is stored is the difference from the defaults** (``exclude_defaults``),
so the default form stores ``None`` and a later default change still applies to
rows that never chose otherwise. An override replaces the defaults for its
event, as in Watcher: an enabled override at defaults stores ``{}``.

**The Jinja fields are on the form** since #367 put the preview beside them, so
the form is the whole truth: a cleared field clears its template, and an
override holding one can be turned off. Each block is validated by
``ContentOptions`` itself, the validator the API and the preview share, so a
template that won't parse is refused in all three places alike.
"""

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from src.core.models.notification_subscription import NOTIFICATION_EVENTS
from src.core.notifications.content import build_body, build_title, resolve_options
from src.core.notifications.content_config import ContentConfig, ContentOptions
from src.core.notifications.default_templates import EVENT_LABELS
from src.core.notifications.preview_fixtures import PREVIEW_ITEM, preview_diff, preview_event

__all__ = [
    "EVENT_LABELS",
    "TEMPLATE_FIELDS",
    "TOGGLES",
    "content_config_from_form",
    "event_labels",
    "options_view",
    "posted_view",
    "render_preview",
]


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
TEMPLATE_FIELDS = (("title_template", "title template"), ("body_template", "body template"))


def options_view(config: dict | None) -> dict[str, Any]:
    """Every option filled in, for the form: ``default`` and ``overrides`` (``None``
    where an event has none), templates included."""
    parsed = ContentConfig.model_validate(config or {})
    return {
        "default": parsed.default.model_dump(),
        "overrides": {
            e: (o.model_dump() if (o := parsed.overrides.get(e)) else None)
            for e in NOTIFICATION_EVENTS
        },
    }


def posted_view(form: Mapping[str, Any]) -> dict[str, Any]:
    """A refused form's blocks as typed, unvalidated, in ``options_view``'s shape.

    So a template that failed to parse is shown again for fixing (CR 2).
    """

    def block(prefix: str) -> dict[str, Any]:
        out: dict[str, Any] = {name: bool(form.get(f"{prefix}__{name}")) for name, _ in TOGGLES}
        out["diff_snippet_lines"] = str(form.get(f"{prefix}__diff_snippet_lines") or "")
        for field, _ in TEMPLATE_FIELDS:
            out[field] = str(form.get(f"{prefix}__{field}") or "").replace("\r\n", "\n")
        return out

    return {
        "default": block("default"),
        "overrides": {
            e: (block(e) if form.get(f"override__{e}") else None) for e in NOTIFICATION_EVENTS
        },
    }


def _label(prefix: str) -> str:
    return "Default" if prefix == "default" else EVENT_LABELS[prefix]


def _template(form: Mapping[str, Any], name: str) -> str | None:
    """A textarea's template: ``None`` when blank, CRLF read as a newline."""
    raw = str(form.get(name) or "").replace("\r\n", "\n")
    return raw if raw.strip() else None


def _block(form: Mapping[str, Any], prefix: str, problems: list[str]) -> ContentOptions | None:
    block: dict[str, Any] = {name: bool(form.get(f"{prefix}__{name}")) for name, _ in TOGGLES}
    raw = str(form.get(f"{prefix}__diff_snippet_lines") or "").strip()
    if raw.isdigit() and 1 <= int(raw) <= 200:
        block["diff_snippet_lines"] = int(raw)
    else:
        problems.append(f"{_label(prefix)}: diff snippet lines must be a whole number, 1-200")
        return None
    for field, _ in TEMPLATE_FIELDS:
        if (source := _template(form, f"{prefix}__{field}")) is not None:
            block[field] = source
    try:
        return ContentOptions(**block)
    except ValidationError as e:
        labels = dict(TEMPLATE_FIELDS)
        for err in e.errors():
            field = labels.get(str(err["loc"][0]), str(err["loc"][0]))
            message = err["msg"].removeprefix("Value error, ")
            problems.append(f"{_label(prefix)}: {field}: {message}")
        return None


def _parse(form: Mapping[str, Any]) -> tuple[ContentConfig | None, list[str]]:
    problems: list[str] = []
    default = _block(form, "default", problems)
    overrides = {
        event: _block(form, event, problems)
        for event in NOTIFICATION_EVENTS
        if form.get(f"override__{event}")
    }
    if problems or default is None:
        return None, problems
    return ContentConfig(default=default, overrides=overrides), []


def content_config_from_form(form: Mapping[str, Any]) -> tuple[dict | None, list[str]]:
    """The ``content_config`` to store, and what would not parse."""
    config, problems = _parse(form)
    if config is None:
        return None, problems
    dumped = config.model_dump(exclude_defaults=True)
    if config.overrides:
        dumped["overrides"] = {
            e: o.model_dump(exclude_defaults=True) for e, o in config.overrides.items()
        }
    return (dumped or None), []


def render_preview(form: Mapping[str, Any], event_type: str) -> dict[str, Any]:
    """The form's options for ``event_type``, rendered strict against the fixtures (D5).

    No Notifier call and no database: the preview is local. ``errors`` holds the
    validator's problems (which the save path would refuse too), or the strict
    render's, which name an undefined variable as well. Those don't block a save:
    a default-block template may name a variable only some events define.
    """
    if event_type not in EVENT_LABELS:
        event_type = NOTIFICATION_EVENTS[0]
    view: dict[str, Any] = {"event": event_type, "title": None, "body": None, "errors": []}
    config, problems = _parse(form)
    if config is None:
        view["errors"] = problems
        return view
    view["block"] = "override" if event_type in config.overrides else "default"
    options = resolve_options(config, event_type)
    event = preview_event(event_type)
    # Any error is the operator's own template's, so it is theirs to see.
    try:
        view["title"] = build_title(event, PREVIEW_ITEM, options, strict=True)
    except Exception as e:
        view["errors"].append(f"Title: {type(e).__name__}: {e}")
    try:
        view["body"] = build_body(
            event, PREVIEW_ITEM, options, strict=True, diff=preview_diff(event_type)
        )
    except Exception as e:
        view["errors"].append(f"Body: {type(e).__name__}: {e}")
    return view
