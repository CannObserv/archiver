"""The built-in title and body templates, and the variables a custom one may use (archiver#367).

Ported from Watcher ``3ba20be`` ``src/core/notifications/default_templates.py``.
**The text is Watcher's, word for word**, so #369's shadow comparison reads like
for like. The ``[Watcher]`` title prefix stays for the same reason, and because
recipients filter on it. Renaming it is an operator decision.

What changed: the variable names follow Archiver's nouns (``info_item_id`` for
``watched_item_id``), and the item link is Archiver's page,
``{{ app_url }}/dashboard/info-items/{{ info_item_id }}``.

For most events a send renders ``DEFAULT_BODY_TEMPLATES[event]`` directly. The
``change_detected`` body is the exception: ``content.build_body`` composes it in
Python from ``CHANGE_DETECTED_HEADER_LINES`` and interleaves the toggle-driven
lines. ``DEFAULT_BODY_TEMPLATES['change_detected']`` comes from the same tuple
and is the seed a person copies into a custom body.
"""

from dataclasses import dataclass

EVENT_LABELS: dict[str, str] = {
    "change_detected": "Change",
    "watch_error": "Error",
    "watch_recovered": "Recovered",
}
"""Watcher's ``EVENT_TITLES``, in declaration order: the ``event_label`` variable."""


@dataclass(frozen=True, slots=True)
class TemplateVariable:
    """One variable a custom title or body may use, as the dashboard lists it."""

    name: str
    type: str
    description: str
    #: ``"always"``, or the one event that defines it.
    scope: str


TEMPLATE_VARIABLES: list[TemplateVariable] = [
    TemplateVariable("info_item_id", "str", "The Information Item's id", "always"),
    TemplateVariable("info_source_id", "str", "The source Watcher checked", "always"),
    TemplateVariable("event_id", "str", "The event's id, unique per occurrence", "always"),
    TemplateVariable("item_name", "str", "The item's name", "always"),
    TemplateVariable("item_url", "str", "The URL Watcher checks (the announcing source)", "always"),
    TemplateVariable("event_type", "str", 'Event code (e.g. "change_detected")', "always"),
    TemplateVariable("event_label", "str", 'Human label (e.g. "Change")', "always"),
    TemplateVariable("occurred_at", "datetime", "When the event occurred (UTC)", "always"),
    TemplateVariable("occurred_at_iso", "str", "The same, as `2026-04-23T00:38:33Z`", "always"),
    TemplateVariable(
        "app_url", "str", "This Archiver's public origin; empty when not configured", "always"
    ),
    TemplateVariable("change_url", "str", "The item's page on a change; empty otherwise", "always"),
    TemplateVariable(
        "diff_snippet",
        "str",
        "On a change, the changed words with context in a ```diff block, capped",
        "always",
    ),
    TemplateVariable("diff_full", "str", "On a change, every change in a ```diff block", "always"),
    TemplateVariable("domain_name", "str", "The announcing source's host", "always"),
    TemplateVariable("check_interval", "str", 'The resolved check cadence (e.g. "1h")', "always"),
    TemplateVariable(
        "last_changed_at", "str", "On a change, this change's time; empty otherwise", "always"
    ),
    TemplateVariable("tags", "list[str]", "The item's tags (none until tags exist)", "always"),
    TemplateVariable("description", "str", "The item's description", "always"),
    TemplateVariable(
        "previous_fingerprint", "str", "sha256 of the previous text", "change_detected"
    ),
    TemplateVariable("current_fingerprint", "str", "sha256 of the current text", "change_detected"),
    TemplateVariable(
        "extraction_changed",
        "str",
        '"spec" when the source spec changed with the content; otherwise empty',
        "change_detected",
    ),
    TemplateVariable(
        "previous_changed_at",
        "str",
        "The change before this one; empty on an item's first change",
        "change_detected",
    ),
    TemplateVariable(
        "reason", "str", "Why the check failed (Watcher's health reason)", "watch_error"
    ),
    TemplateVariable(
        "status_code", "int", "The HTTP status; undefined when none came back", "watch_error"
    ),
    TemplateVariable(
        "renotify", "bool", "True on a reminder that it is still failing", "watch_error"
    ),
    TemplateVariable(
        "previously_notified_at",
        "str",
        "On a reminder, the last error notification's time; empty otherwise",
        "watch_error",
    ),
    TemplateVariable(
        "error_since", "str", "When the error began; empty when unknown", "watch_recovered"
    ),
]
"""Every variable ``content.build_template_context`` defines, and nothing else
(``test_the_context_is_built_field_by_field``)."""

_TITLE = "[Watcher] {{ event_label }}: {{ item_name }}"

DEFAULT_TITLE_TEMPLATES: dict[str, str] = {event: _TITLE for event in EVENT_LABELS}

#: The item link. A template, not a URL: the origin is ``ARCHIVER_PUBLIC_BASE_URL``,
#: rendered per deployment as ``app_url``. The composer drops this line when no
#: origin is configured, which is why it is a named constant.
CHANGE_DETECTED_ITEM_LINE = "ITEM: {{ app_url }}/dashboard/info-items/{{ info_item_id }}"

# The composer's insertion anchors (``content._build_change_detected_body``):
#   - DOMAIN: right after item_name (index 1)
#   - PREVIOUS CHANGE, INTERVAL: right before TIMESTAMP, in that order
# Reorder this tuple and the composer's anchors must follow.
CHANGE_DETECTED_HEADER_LINES: tuple[str, ...] = (
    "{{ item_name }}",
    "URL: {{ item_url }}",
    "TIMESTAMP: {{ occurred_at_iso }}",
    CHANGE_DETECTED_ITEM_LINE,
)


def _seed_bullets(lines: tuple[str, ...]) -> str:
    """The header as a Markdown list, the ITEM bullet guarded on ``app_url``.

    The guard holds the newline too, so no empty bullet is left without an origin.
    """
    parts: list[str] = []
    for index, line in enumerate(lines):
        bullet = f"{'' if index == 0 else chr(10)}- {line}"
        if line == CHANGE_DETECTED_ITEM_LINE:
            bullet = f"{{% if app_url %}}{bullet}{{% endif %}}"
        parts.append(bullet)
    return "".join(parts)


DEFAULT_BODY_TEMPLATES: dict[str, str] = {
    "change_detected": _seed_bullets(CHANGE_DETECTED_HEADER_LINES),
    # A reminder (#369) says so after a blank line, so an HTML channel renders it
    # as its own paragraph.
    "watch_error": (
        "{{ item_url }} returned HTTP {{ status_code | default('unknown') }}"
        "{% if renotify is defined and renotify %}\n\nStill failing"
        "{% if previously_notified_at %}"
        " — previously notified {{ previously_notified_at }}{% endif %}."
        "{% endif %}"
    ),
    "watch_recovered": "{{ item_url }} is responding normally again",
}


def compose_title_prefill(event_type: str) -> str:
    """The default title template, to seed a custom one."""
    return DEFAULT_TITLE_TEMPLATES[event_type]


def compose_body_prefill(event_type: str) -> str:
    """The default body template, to seed a custom one. Toggles don't affect it."""
    return DEFAULT_BODY_TEMPLATES[event_type]
