"""The composer (archiver#367, D1-D2): an event, its item's facts and one row's options in;
a title and a body out. Pure: no database, no store, no Notifier.

Ported from Watcher ``3ba20be`` ``src/core/notifications/content.py``. The layout,
the toggles, the diff block and its caps are Watcher's, so #369's shadow
comparison reads like for like. Three things differ, on purpose:

- **The context is built field by field** from co-core's event and
  :class:`ItemFacts` (D1). Watcher flattened ``event.metadata`` into it, so a key
  on the wire could become a template variable by accident. ``TEMPLATE_VARIABLES``
  lists every variable, and a test holds the two equal.
- **Every render is sandboxed** (``SandboxedEnvironment``, defaults included), and
  **nothing returns template source** (D2). Watcher's ``render_template``
  returned the raw template on an error, which sent an operator's Jinja to Slack.
  Here a render raises. :func:`compose`, the send path, renders that event's
  default instead and logs a WARNING naming the subscription and the error's
  type. The template's text never reaches a log. The preview renders strict
  (``strict=True``) and shows the error.
- **Links point at Archiver's item page**, ``{origin}/dashboard/info-items/{id}``,
  from ``ARCHIVER_PUBLIC_BASE_URL``. Unset means no link.

The composed text reaches Notifier only as variables, never as its template
(D3, ``src.core.notifier.client.Notifier.dispatch_composed``).
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from co_core.pure.models.changes import (
    ChangeDetectedEvent,
    WatchErrorEvent,
    WatchRecoveredEvent,
)
from jinja2 import StrictUndefined
from jinja2.exceptions import SecurityError
from jinja2.sandbox import SandboxedEnvironment

from src.core.logging import get_logger
from src.core.notifications.content_config import ContentConfig, ContentOptions
from src.core.notifications.default_templates import (
    CHANGE_DETECTED_HEADER_LINES,
    CHANGE_DETECTED_ITEM_LINE,
    DEFAULT_BODY_TEMPLATES,
    DEFAULT_TITLE_TEMPLATES,
    EVENT_LABELS,
)
from src.core.notifications.diff import ChangeDiff, Hunk
from src.core.public_base_url import item_page_url, public_base_url

logger = get_logger(__name__)

WatchEvent = ChangeDetectedEvent | WatchErrorEvent | WatchRecoveredEvent
"""The three ``info.watch-events`` facts a subscription can hear, as co-core models them."""

#: The longest string or list one ``*`` may build in a template (CR 1).
MAX_REPEAT_LENGTH = 100_000
#: The largest exponent one ``**`` may take in a template (CR 1).
MAX_EXPONENT = 100


class _BoundedSandbox(SandboxedEnvironment):
    """The sandbox, with ``*`` and ``**`` bounded (CR 1).

    ``SandboxedEnvironment`` stops attribute escapes and caps ``range``, but
    ``'x' * 10**9`` still allocates a gigabyte in the one process that serves
    the API, the consumers and the dashboard. Jinja routes these two operators
    through :meth:`call_binop` once they are intercepted, and doesn't fold them
    at compile time, so every template pays the check.
    """

    intercepted_binops = frozenset({"*", "**"})

    def call_binop(self, context, operator: str, left: Any, right: Any) -> Any:
        if operator == "**":
            if isinstance(right, int | float) and abs(right) > MAX_EXPONENT:
                raise SecurityError(f"exponent over {MAX_EXPONENT}")
        elif operator == "*":
            for seq, n in ((left, right), (right, left)):
                if isinstance(seq, str | list | tuple) and isinstance(n, int):
                    if len(seq) * n > MAX_REPEAT_LENGTH:
                        raise SecurityError(f"repetition over {MAX_REPEAT_LENGTH} items")
        return super().call_binop(context, operator, left, right)


_SANDBOX = _BoundedSandbox(autoescape=False)
_SANDBOX_STRICT = _BoundedSandbox(autoescape=False, undefined=StrictUndefined)

# The ``diff_snippet`` variable's cap when a template names it: the field's default.
_DEFAULT_DIFF_SNIPPET_CAP: int = ContentOptions.model_fields["diff_snippet_lines"].default

#: The most a rendered diff block may be, fences and footer included (Watcher
#: #346/#349). Under Slack's 40 000-character message limit and Gmail's 102 KB
#: clip, with room for the header. Notifier publishes no request limit.
MAX_RENDERED_DIFF_BYTES = 32 * 1024
# Room kept for the `... (N more lines)` footer and its newline.
_FOOTER_BYTES = 32

_BACKTICK_RUN = re.compile(r"`+")

#: Watcher's #326 D6 label: the spec that bound moved between the two revisions,
#: so part of the difference may be the selector's, not the page's.
SPEC_CHANGED_NOTE = (
    "NOTE: the source spec changed — some of this difference may come from the new selector"
)


@dataclass(frozen=True, slots=True)
class ItemFacts:
    """What the composer knows about the item, beyond the event.

    Built by ``item_facts.load_item_facts`` (D1): the name and description are
    the InfoItem's; the URL and ``domain_name`` are its announcing source's;
    ``check_interval`` is the resolved cadence. ``""`` means unknown.
    """

    name: str
    url: str = ""
    domain_name: str = ""
    description: str = ""
    check_interval: str = ""
    #: Inert until tags exist (#362).
    tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Composed:
    """One notification's text, ready for Notifier."""

    title: str
    body: str


def format_utc_iso(dt: datetime) -> str:
    """ISO 8601 with a ``Z`` (AGENTS.md); naive is read as UTC; microseconds kept."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _iso_or_empty(dt: datetime | None) -> str:
    return format_utc_iso(dt) if dt is not None else ""


def render_template(source: str, context: Mapping[str, Any]) -> str:
    """Render in the sandbox; an undefined variable is empty. Raises on any error."""
    return _SANDBOX.from_string(source).render(context)


def render_template_strict(source: str, context: Mapping[str, Any]) -> str:
    """Render in the sandbox; an undefined variable raises too. The preview's render."""
    return _SANDBOX_STRICT.from_string(source).render(context)


def resolve_options(
    config: ContentConfig | Mapping[str, Any] | None, event_type: str
) -> ContentOptions:
    """The options that apply to ``event_type``: its override, else ``default``.

    ``config`` may be the stored ``content_config`` document; ``None`` is all defaults.
    """
    if config is None:
        return ContentOptions()
    if not isinstance(config, ContentConfig):
        config = ContentConfig.model_validate(config)
    return config.overrides.get(event_type) or config.default


def build_template_context(
    event: WatchEvent,
    item: ItemFacts,
    *,
    diff: ChangeDiff | None = None,
    diff_snippet_cap: int = _DEFAULT_DIFF_SNIPPET_CAP,
    previously_notified_at: datetime | None = None,
) -> dict[str, Any]:
    """Every variable a template sees, field by field (D1). ``TEMPLATE_VARIABLES`` lists them.

    Absent values are ``""``, never ``None``, which a lenient render would print.
    One exception: a null ``status_code`` is left **undefined**, so Watcher's
    ``status_code | default('unknown')`` still reads "unknown".

    ``diff_snippet`` and ``diff_full`` are empty without a ``diff``, and read
    ``(diff unavailable: <reason>)`` when one was tried and could not be made.
    ``previously_notified_at`` marks a ``watch_error`` as a reminder (#369).
    """
    base = public_base_url() or ""
    is_change = isinstance(event, ChangeDetectedEvent)
    ctx: dict[str, Any] = {
        "info_item_id": event.info_item_id,
        "info_source_id": event.info_source_id,
        "event_id": event.event_id,
        "item_name": item.name,
        "item_url": item.url,
        "event_type": event.event_type,
        "event_label": EVENT_LABELS[event.event_type],
        "occurred_at": event.occurred_at,
        "occurred_at_iso": format_utc_iso(event.occurred_at),
        "app_url": base,
        "change_url": item_page_url(base, event.info_item_id) if base and is_change else "",
        "diff_snippet": _render_diff_variable(diff, max_lines=diff_snippet_cap),
        "diff_full": _render_diff_variable(diff, max_lines=None),
        "domain_name": item.domain_name,
        "check_interval": item.check_interval,
        # Archiver keeps no item-level last change: on a change it is this one
        # (Watcher #349); otherwise unknown.
        "last_changed_at": format_utc_iso(event.occurred_at) if is_change else "",
        "tags": list(item.tags),
        "description": item.description,
    }
    if isinstance(event, ChangeDetectedEvent):
        ctx |= {
            "previous_fingerprint": event.previous_fingerprint,
            "current_fingerprint": event.current_fingerprint,
            "extraction_changed": event.extraction_changed or "",
            "previous_changed_at": _iso_or_empty(event.previous_changed_at),
        }
    elif isinstance(event, WatchErrorEvent):
        ctx |= {
            "reason": event.reason,
            "renotify": previously_notified_at is not None,
            "previously_notified_at": _iso_or_empty(previously_notified_at),
        }
        if event.status_code is not None:
            ctx["status_code"] = event.status_code
    else:
        ctx["error_since"] = _iso_or_empty(event.error_since)
    return ctx


def build_title(
    event: WatchEvent, item: ItemFacts, options: ContentOptions, *, strict: bool = False
) -> str:
    """The title: ``options.title_template`` if set, else the event's default.

    Raises on a failing template; :func:`compose` is the send path that doesn't.
    """
    source = options.title_template or DEFAULT_TITLE_TEMPLATES[event.event_type]
    render = render_template_strict if strict else render_template
    return render(source, build_template_context(event, item))


def build_body(
    event: WatchEvent,
    item: ItemFacts,
    options: ContentOptions,
    *,
    strict: bool = False,
    diff: ChangeDiff | None = None,
    previously_notified_at: datetime | None = None,
) -> str:
    """The body, by one of three paths. Raises on a failing custom template.

    1. ``options.body_template`` set: render it. The toggles don't apply, but the
       row's ``diff_snippet_lines`` caps ``{{ diff_snippet }}``.
    2. ``change_detected``: :func:`_build_change_detected_body` composes the
       header and the toggle-driven lines in Python, then the diff.
    3. otherwise: render ``DEFAULT_BODY_TEMPLATES[event]``. Toggles don't apply.

    ``diff`` is this event's: #369 loads it (``diff_loader``), the preview computes
    it from canned text. ``None`` means none was computed.
    """
    if options.body_template:
        render = render_template_strict if strict else render_template
        ctx = build_template_context(
            event,
            item,
            diff=diff,
            diff_snippet_cap=options.diff_snippet_lines,
            previously_notified_at=previously_notified_at,
        )
        return render(options.body_template, ctx)
    return _default_body(
        event, item, options, diff=diff, previously_notified_at=previously_notified_at
    )


def compose(
    event: WatchEvent,
    item: ItemFacts,
    options: ContentOptions,
    *,
    diff: ChangeDiff | None = None,
    previously_notified_at: datetime | None = None,
    subscription_id: str | None = None,
) -> Composed:
    """The send path (D2): a custom template that fails renders the event's default.

    Lenient, as in Watcher: an undefined variable renders empty. Anything a
    custom template raises (a syntax error, the sandbox's refusal, a runtime
    error) falls back per field, with a WARNING naming the subscription and the
    error's type, never the template or the error's text, which can quote it.
    """
    try:
        title = build_title(event, item, options)
    except Exception as e:
        _warn_fallback("title", e, event, subscription_id)
        title = render_template(
            DEFAULT_TITLE_TEMPLATES[event.event_type], build_template_context(event, item)
        )
    try:
        body = build_body(
            event, item, options, diff=diff, previously_notified_at=previously_notified_at
        )
    except Exception as e:
        _warn_fallback("body", e, event, subscription_id)
        body = _default_body(
            event, item, options, diff=diff, previously_notified_at=previously_notified_at
        )
    return Composed(title=title, body=body)


def _warn_fallback(field: str, error: Exception, event: WatchEvent, subscription_id) -> None:
    logger.warning(
        "custom notification %s failed to render; sending the default",
        field,
        extra={
            "subscription_id": subscription_id,
            "event_type": event.event_type,
            "info_item_id": event.info_item_id,
            "field": field,
            "error_type": type(error).__name__,
        },
    )


def _default_body(
    event: WatchEvent,
    item: ItemFacts,
    options: ContentOptions,
    *,
    diff: ChangeDiff | None,
    previously_notified_at: datetime | None,
) -> str:
    if isinstance(event, ChangeDetectedEvent):
        return _build_change_detected_body(event, item, options, diff=diff)
    ctx = build_template_context(event, item, previously_notified_at=previously_notified_at)
    return render_template(DEFAULT_BODY_TEMPLATES[event.event_type], ctx)


def _build_change_detected_body(
    event: ChangeDetectedEvent, item: ItemFacts, options: ContentOptions, *, diff: ChangeDiff | None
) -> str:
    """The change body: a Markdown bullet list, then the diff as a fenced block.

    Every fact is a list item: Notifier renders the body through CommonMark for
    HTML channels, where a lone ``\\n`` is a soft break (Watcher #224/#225).

    Fact order; ``?`` items are toggle- or value-gated:
      item_name, DOMAIN?, URL, PREVIOUS CHANGE?, INTERVAL?, TIMESTAMP, ITEM?,
      NOTE?, DESCRIPTION?, TAGS?, DIFF?

    ITEM needs a configured origin. NOTE is ``extraction_changed == "spec"``,
    not a toggle: it qualifies the change itself. DIFF is the one-line
    "unavailable (<reason>)" when a requested diff could not be made.
    """
    ctx = build_template_context(event, item)
    items = [
        render_template(line, ctx)
        for line in CHANGE_DETECTED_HEADER_LINES
        if ctx["app_url"] or line != CHANGE_DETECTED_ITEM_LINE
    ]
    if options.include_domain and item.domain_name:
        items.insert(1, f"DOMAIN: {item.domain_name}")

    timestamp_idx = next(i for i, line in enumerate(items) if line.startswith("TIMESTAMP:"))
    pre_timestamp: list[str] = []
    if options.include_last_changed_at and event.previous_changed_at is not None:
        pre_timestamp.append(f"PREVIOUS CHANGE: {format_utc_iso(event.previous_changed_at)}")
    if options.include_temporal_context and item.check_interval:
        pre_timestamp.append(f"INTERVAL: {item.check_interval}")
    items[timestamp_idx:timestamp_idx] = pre_timestamp

    if event.extraction_changed == "spec":
        items.append(SPEC_CHANGED_NOTE)
    if options.include_description and item.description:
        items.append(f"DESCRIPTION: {item.description}")
    if options.include_tags and item.tags:
        items.append(f"TAGS: {', '.join(item.tags)}")
    wants_diff = options.include_diff_snippet or options.include_diff_full
    if wants_diff and diff is not None and diff.unavailable:
        items.append(f"DIFF: unavailable ({diff.unavailable})")

    listing = "\n".join(f"- {line}" for line in items)
    diff_text = _build_diff_text(diff, options)
    return f"{listing}\n\n{diff_text}" if diff_text else listing


# --- The diff block: Watcher's, unchanged -------------------------------------


def _build_diff_text(diff: ChangeDiff | None, options: ContentOptions) -> str:
    """The diff block under the toggles; empty when neither is on or there is none."""
    if not (options.include_diff_snippet or options.include_diff_full):
        return ""
    if diff is None or diff.unavailable:
        return ""
    cap = None if options.include_diff_full else options.diff_snippet_lines
    return _render_diff_block(diff.hunks, max_lines=cap)


def _render_diff_variable(diff: ChangeDiff | None, *, max_lines: int | None) -> str:
    """One diff template variable: the fenced block, the reason, or empty."""
    if diff is None:
        return ""
    if diff.unavailable:
        return f"(diff unavailable: {diff.unavailable})"
    return _render_diff_block(diff.hunks, max_lines=max_lines)


def _render_diff_block(hunks: tuple[Hunk, ...], *, max_lines: int | None) -> str:
    """The hunks in a Markdown ```diff block, an empty line between two.

    ``max_lines=None`` means every hunk; otherwise cut on a hunk boundary. The
    whole block, fences included, stays within ``MAX_RENDERED_DIFF_BYTES``: the
    body is cut once against a minimal fence and, if the real fence overflows,
    once more to a third of the cap (Watcher CR 2). Empty without hunks.
    """
    if not hunks:
        return ""
    block = _fenced_block(hunks, max_lines, MAX_RENDERED_DIFF_BYTES - _fence_bytes("```"))
    if len(block.encode()) > MAX_RENDERED_DIFF_BYTES:
        budget = (MAX_RENDERED_DIFF_BYTES - _fence_bytes("") - 2) // 3
        block = _fenced_block(hunks, max_lines, budget)
    return block


def _fence_bytes(fence: str) -> int:
    """What a fence adds around a body: both fences, the info string, two newlines."""
    return 2 * len(fence) + len("diff") + 2


def _fenced_block(hunks: tuple[Hunk, ...], max_lines: int | None, max_bytes: int) -> str:
    kept, omitted = _truncate_hunks(hunks, max_lines=max_lines, max_bytes=max_bytes)
    if omitted:
        kept = [*kept, f"... ({omitted} more line{'s' if omitted != 1 else ''})"]
    body = "\n".join(kept)
    fence = _fence_for(body)
    return f"{fence}diff\n{body}\n{fence}"


def _fence_for(body: str) -> str:
    """A backtick fence no line of ``body`` can close (Watcher CR 13/14).

    The diff is the watched page's own text, and CommonMark closes a fence on a
    line that is only a run at least as long. One longer than the longest run in
    the content (three at minimum) means no line can close it.
    """
    longest = max((len(run) for run in _BACKTICK_RUN.findall(body)), default=0)
    return "`" * max(3, longest + 1)


def _joined_size(lines: list[str]) -> int:
    return len("\n".join(lines).encode())


def _truncate_hunks(
    hunks: tuple[Hunk, ...], *, max_lines: int | None, max_bytes: int
) -> tuple[list[str], int]:
    """The hunks' lines, cut to fit, and how many lines were not shown in full.

    Hunks are separated by an empty line, which counts toward ``max_lines`` but
    never as an omitted line. When everything fits it is returned whole.
    Otherwise one line and ``_FOOTER_BYTES`` are kept back for the footer, and
    whole hunks are kept while they fit. If not even the first does, its leading
    lines are kept instead, the last cut within the line when one alone outgrows
    the bytes. ``0`` omitted means nothing was cut.
    """
    every = [line for index, hunk in enumerate(hunks) for line in (*([""] if index else []), *hunk)]
    if (max_lines is None or len(every) <= max_lines) and _joined_size(every) <= max_bytes:
        return every, 0

    line_budget = None if max_lines is None else max_lines - 1
    byte_budget = max_bytes - _FOOTER_BYTES

    def fits(lines: list[str]) -> bool:
        within_lines = line_budget is None or len(lines) <= line_budget
        return within_lines and _joined_size(lines) <= byte_budget

    kept: list[str] = []
    for hunk in hunks:
        candidate = [*kept, *([""] if kept else []), *hunk]
        if not fits(candidate):
            break
        kept = candidate
    shown = sum(1 for line in kept if line)
    if not kept:
        for line in hunks[0]:
            if line_budget is not None and len(kept) >= line_budget:
                break
            if fits([*kept, line]):
                kept.append(line)
                shown += 1
                continue
            room = byte_budget - _joined_size([*kept, ""])
            if room > len("…".encode()):
                cut = line.encode()[: room - len("…".encode())].decode(errors="ignore")
                kept.append(f"{cut}…")
            break
    total = sum(len(hunk) for hunk in hunks)
    return kept, total - shown
