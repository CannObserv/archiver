"""The composer (archiver#367): an event, its item's facts and one row's options in;
a title and a body out.

Ported from Watcher ``3ba20be`` ``tests/core/notifications/test_content.py``. The
cases are Watcher's, re-expressed over co-core's events and ``ItemFacts``, where
Watcher had a ``WatchEvent`` and a metadata dict. What changed and why:

- **The context is built field by field** (D1). Watcher flattened the event's
  metadata into it; here no wire key becomes a variable by accident.
- **Every render is sandboxed** (D2). Watcher's ``render_template`` returned the
  raw template on an error, which sent an operator's Jinja to Slack. Here a
  render raises, and :func:`compose` (the send path) falls back to the event's
  default with a WARNING naming the subscription.
- **Links point at Archiver's item page**, ``{origin}/dashboard/info-items/{id}``.
"""

import logging
import re
from datetime import UTC, datetime

import pytest
from jinja2 import TemplateError, UndefinedError
from jinja2.exceptions import SecurityError

from src.core.notifications.content import (
    MAX_RENDERED_DIFF_BYTES,
    SPEC_CHANGED_NOTE,
    Composed,
    ItemFacts,
    _truncate_hunks,
    build_body,
    build_template_context,
    build_title,
    compose,
    render_template,
    render_template_strict,
    resolve_options,
)
from src.core.notifications.content_config import ContentConfig, ContentOptions
from src.core.notifications.default_templates import (
    DEFAULT_BODY_TEMPLATES,
    EVENT_LABELS,
    TEMPLATE_VARIABLES,
    compose_body_prefill,
)
from src.core.notifications.diff import ChangeDiff, compute_change_diff
from src.core.public_base_url import PUBLIC_BASE_URL_ENV
from tests.core.notifications.builders import (
    CURRENT_FP,
    EVENT_ID,
    ITEM,
    ITEM_ID,
    PREVIOUS_FP,
    SOURCE_ID,
    make_event,
)

#: A host that is no deployment's, so no expected string here can be mistaken
#: for where the dashboard actually lives.
BASE = "https://archiver.test"
ITEM_PAGE = f"{BASE}/dashboard/info-items/{ITEM_ID}"
EVENTS = ("change_detected", "watch_error", "watch_recovered")

FULL_ITEM = ItemFacts(
    name="Test Item",
    url="https://example.com",
    domain_name="example.com",
    description="Watch for license renewals",
    check_interval="1h",
    tags=("cannabis", "license"),
)


@pytest.fixture(autouse=True)
def _public_base_url(monkeypatch):
    """Every test renders against a configured base unless it removes it."""
    monkeypatch.setenv(PUBLIC_BASE_URL_ENV, BASE)


class TestResolveOptions:
    def test_none_config_returns_defaults(self):
        assert resolve_options(None, "change_detected") == ContentOptions()

    def test_default_used_when_no_override(self):
        cfg = ContentConfig(default=ContentOptions(include_domain=True))
        assert resolve_options(cfg, "change_detected").include_domain is True

    def test_override_takes_precedence(self):
        cfg = ContentConfig(
            default=ContentOptions(include_domain=True),
            overrides={"change_detected": ContentOptions(include_domain=False)},
        )
        assert resolve_options(cfg, "change_detected").include_domain is False

    def test_non_overridden_event_falls_back_to_default(self):
        cfg = ContentConfig(
            default=ContentOptions(include_domain=True),
            overrides={"watch_error": ContentOptions(include_domain=False)},
        )
        assert resolve_options(cfg, "change_detected").include_domain is True

    def test_a_stored_document_is_accepted(self):
        """The row's ``content_config`` column, as stored."""
        stored = {"overrides": {"watch_error": {"include_domain": True}}}
        assert resolve_options(stored, "watch_error").include_domain is True
        assert resolve_options(stored, "change_detected") == ContentOptions()


class TestChangeDetectedDefaultBody:
    def test_default_skeleton_with_no_toggles(self):
        body = build_body(make_event(), ITEM, ContentOptions())
        assert body == (
            "- Test Item\n"
            "- URL: https://example.com\n"
            "- TIMESTAMP: 2026-04-14T12:00:00Z\n"
            f"- ITEM: {ITEM_PAGE}"
        )

    def test_item_link_follows_the_configured_base(self, monkeypatch):
        monkeypatch.setenv(PUBLIC_BASE_URL_ENV, "https://co-registrar.exe.xyz/")
        body = build_body(make_event(), ITEM, ContentOptions())
        assert f"- ITEM: https://co-registrar.exe.xyz/dashboard/info-items/{ITEM_ID}" in body

    def test_item_link_is_omitted_without_a_base(self, monkeypatch):
        monkeypatch.delenv(PUBLIC_BASE_URL_ENV)
        body = build_body(make_event(), ITEM, ContentOptions())
        assert body == (
            "- Test Item\n- URL: https://example.com\n- TIMESTAMP: 2026-04-14T12:00:00Z"
        )

    @pytest.mark.parametrize(
        "value", ["co-registrar.exe.xyz", "https://[co-registrar", "https://x.test/dashboard"]
    )
    def test_a_malformed_base_never_breaks_a_send(self, monkeypatch, value):
        monkeypatch.setenv(PUBLIC_BASE_URL_ENV, value)
        body = build_body(make_event(), ITEM, ContentOptions())
        assert "ITEM:" not in body
        assert body.startswith("- Test Item")

    def test_full_layout_with_every_toggle_on(self):
        event = make_event(previous_changed_at=datetime(2026, 4, 9, tzinfo=UTC))
        opts = ContentOptions(
            include_temporal_context=True,
            include_domain=True,
            include_last_changed_at=True,
            include_description=True,
            include_tags=True,
        )
        assert build_body(event, FULL_ITEM, opts) == (
            "- Test Item\n"
            "- DOMAIN: example.com\n"
            "- URL: https://example.com\n"
            "- PREVIOUS CHANGE: 2026-04-09T00:00:00Z\n"
            "- INTERVAL: 1h\n"
            "- TIMESTAMP: 2026-04-14T12:00:00Z\n"
            f"- ITEM: {ITEM_PAGE}\n"
            "- DESCRIPTION: Watch for license renewals\n"
            "- TAGS: cannabis, license"
        )

    def test_minimal_facts_render_under_strict(self):
        body = build_body(make_event(), ITEM, ContentOptions(include_domain=True), strict=True)
        assert "Test Item" in body
        assert "DOMAIN" not in body

    def test_seed_template_matches_the_composed_body_with_default_options(self):
        """The seed shown to the operator renders exactly what a send composes."""
        event = make_event()
        seed = render_template(
            DEFAULT_BODY_TEMPLATES["change_detected"], build_template_context(event, ITEM)
        )
        assert seed == build_body(event, ITEM, ContentOptions())

    def test_seed_matches_the_composed_body_without_a_base(self, monkeypatch):
        monkeypatch.delenv(PUBLIC_BASE_URL_ENV, raising=False)
        event = make_event()
        seed = render_template(
            DEFAULT_BODY_TEMPLATES["change_detected"], build_template_context(event, ITEM)
        )
        assert "/info-items/" not in seed
        assert seed == build_body(event, ITEM, ContentOptions())
        custom = ContentOptions(body_template=compose_body_prefill("change_detected"))
        assert "ITEM:" not in build_body(event, ITEM, custom)


class TestDomainSlot:
    def test_renders_between_name_and_url_when_toggle_on(self):
        lines = build_body(make_event(), FULL_ITEM, ContentOptions(include_domain=True)).split("\n")
        assert lines[:3] == ["- Test Item", "- DOMAIN: example.com", "- URL: https://example.com"]

    def test_omitted_when_toggle_off(self):
        assert "DOMAIN" not in build_body(make_event(), FULL_ITEM, ContentOptions())

    def test_omitted_when_the_item_has_no_domain(self):
        assert "DOMAIN" not in build_body(make_event(), ITEM, ContentOptions(include_domain=True))


class TestStatsSlots:
    def test_interval_renders_with_label_when_toggle_on(self):
        body = build_body(make_event(), FULL_ITEM, ContentOptions(include_temporal_context=True))
        assert "INTERVAL: 1h" in body

    def test_previous_change_renders_with_label_when_toggle_on(self):
        event = make_event(previous_changed_at=datetime(2026, 4, 9, 17, 45, tzinfo=UTC))
        body = build_body(event, ITEM, ContentOptions(include_last_changed_at=True))
        assert "PREVIOUS CHANGE: 2026-04-09T17:45:00Z" in body

    def test_previous_change_and_interval_render_between_url_and_timestamp(self):
        event = make_event(previous_changed_at=datetime(2026, 4, 9, tzinfo=UTC))
        body = build_body(
            event,
            FULL_ITEM,
            ContentOptions(include_temporal_context=True, include_last_changed_at=True),
        )
        assert (
            "- URL: https://example.com\n- PREVIOUS CHANGE: 2026-04-09T00:00:00Z\n"
            "- INTERVAL: 1h\n- TIMESTAMP: "
        ) in body

    def test_stats_omitted_when_toggles_off(self):
        event = make_event(previous_changed_at=datetime(2026, 4, 9, tzinfo=UTC))
        body = build_body(event, FULL_ITEM, ContentOptions())
        assert "INTERVAL" not in body
        assert "PREVIOUS CHANGE" not in body

    def test_stats_omitted_on_an_items_first_change(self):
        body = build_body(
            make_event(previous_changed_at=None),
            ITEM,
            ContentOptions(include_temporal_context=True, include_last_changed_at=True),
        )
        assert "INTERVAL" not in body
        assert "PREVIOUS CHANGE" not in body


class TestDescriptionAndTagsSlots:
    def test_description_renders_with_label_when_toggle_on(self):
        body = build_body(make_event(), FULL_ITEM, ContentOptions(include_description=True))
        assert "DESCRIPTION: Watch for license renewals" in body

    def test_description_omitted_when_toggle_off_or_empty(self):
        assert "DESCRIPTION" not in build_body(make_event(), FULL_ITEM, ContentOptions())
        opts = ContentOptions(include_description=True)
        assert "DESCRIPTION" not in build_body(make_event(), ITEM, opts)

    def test_tags_render_comma_joined_when_toggle_on(self):
        body = build_body(make_event(), FULL_ITEM, ContentOptions(include_tags=True))
        assert "TAGS: cannabis, license" in body

    def test_tags_omitted_when_toggle_off_or_none(self):
        """Inert until tags exist (#362): no item has any yet."""
        assert "TAGS" not in build_body(make_event(), FULL_ITEM, ContentOptions())
        assert "TAGS" not in build_body(make_event(), ITEM, ContentOptions(include_tags=True))


class TestExtractionChangedLabel:
    def test_a_spec_change_carries_the_note(self):
        body = build_body(make_event(extraction_changed="spec"), ITEM, ContentOptions())
        assert f"- {SPEC_CHANGED_NOTE}" in body.split("\n")

    @pytest.mark.parametrize("value", [None, "processor"])
    def test_anything_else_carries_none(self, value):
        body = build_body(make_event(extraction_changed=value), ITEM, ContentOptions())
        assert SPEC_CHANGED_NOTE not in body

    def test_the_note_names_the_cause(self):
        assert "source spec changed" in SPEC_CHANGED_NOTE


class TestMarkdownListContract:
    """Notifier renders the body through CommonMark for HTML channels, where a lone
    ``\\n`` is a soft break: every fact must be its own list item (Watcher #224/#225)."""

    def test_every_line_is_a_list_item_with_every_fact(self):
        event = make_event(previous_changed_at=datetime(2026, 4, 9, tzinfo=UTC))
        opts = ContentOptions(
            include_temporal_context=True,
            include_domain=True,
            include_last_changed_at=True,
            include_description=True,
            include_tags=True,
        )
        for line in build_body(event, FULL_ITEM, opts).split("\n"):
            assert line.startswith("- "), line

    def test_skeleton_is_a_tight_list(self):
        body = build_body(make_event(), ITEM, ContentOptions())
        assert "\n\n" not in body


class TestNonChangeDefaultBodies:
    """Watcher's default text, word for word, so #369's shadow compares like for like."""

    def test_watch_error_renders_default_template(self):
        event = make_event("watch_error", status_code=500)
        body = build_body(event, ITEM, ContentOptions(include_domain=True))
        assert body == "https://example.com returned HTTP 500"

    def test_watch_error_without_a_status_says_unknown(self):
        """``status_code`` is null when the origin never answered (a DNS failure)."""
        body = build_body(make_event("watch_error", status_code=None), ITEM, ContentOptions())
        assert body == "https://example.com returned HTTP unknown"

    def test_a_first_watch_error_carries_no_reminder(self):
        event = make_event("watch_error", status_code=500)
        body = build_body(event, ITEM, ContentOptions(), strict=True)
        assert body == "https://example.com returned HTTP 500"

    def test_a_reminder_says_it_is_one(self):
        """#369 feeds the last notification's time; the composer only words it."""
        event = make_event("watch_error", status_code=500)
        body = build_body(
            event,
            ITEM,
            ContentOptions(),
            strict=True,
            previously_notified_at=datetime(2026, 10, 8, 12, tzinfo=UTC),
        )
        assert body == (
            "https://example.com returned HTTP 500\n\n"
            "Still failing — previously notified 2026-10-08T12:00:00Z."
        )

    def test_watch_recovered_renders_default_template(self):
        body = build_body(make_event("watch_recovered"), ITEM, ContentOptions())
        assert body == "https://example.com is responding normally again"


class TestSandbox:
    """D2: every render is sandboxed, the defaults included. A template arrives
    through an API key, and Watcher's plain ``Environment`` reached Python attributes."""

    ESCAPE = "{{ ''.__class__.__mro__[1].__subclasses__() }}"

    def test_an_attribute_escape_is_refused(self):
        with pytest.raises(SecurityError):
            render_template(self.ESCAPE, {})
        with pytest.raises(SecurityError):
            render_template_strict(self.ESCAPE, {})

    def test_lenient_renders_an_undefined_variable_empty(self):
        assert render_template("[{{ missing }}]", {}) == "[]"

    def test_strict_raises_on_an_undefined_variable(self):
        with pytest.raises(UndefinedError):
            render_template_strict("{{ missing }}", {})

    def test_neither_swallows_a_syntax_error(self):
        """Watcher returned the template source here, and sent it."""
        for render in (render_template, render_template_strict):
            with pytest.raises(TemplateError):
                render("{{ unclosed", {})

    def test_a_value_is_never_evaluated(self):
        assert render_template("{{ body }}", {"body": "{{ x }}{% if %}"}) == "{{ x }}{% if %}"


class TestBuildTemplateContext:
    def test_the_always_present_variables(self, monkeypatch):
        ctx = build_template_context(make_event(), ITEM)
        assert ctx["info_item_id"] == ITEM_ID
        assert ctx["info_source_id"] == SOURCE_ID
        assert ctx["event_id"] == EVENT_ID
        assert ctx["item_name"] == "Test Item"
        assert ctx["item_url"] == "https://example.com"
        assert ctx["event_type"] == "change_detected"
        assert ctx["event_label"] == "Change"
        assert ctx["occurred_at_iso"] == "2026-04-14T12:00:00Z"
        assert ctx["app_url"] == BASE

    def test_the_context_is_built_field_by_field(self):
        """D1: exactly the documented variables per event. A key on the wire must
        never become a template variable by accident."""
        fields = {"watch_error": {"status_code": 503}}
        for event_type in EVENTS:
            ctx = build_template_context(make_event(event_type, **fields.get(event_type, {})), ITEM)
            documented = {v.name for v in TEMPLATE_VARIABLES if v.scope in {"always", event_type}}
            assert set(ctx) == documented, event_type

    def test_change_variables(self):
        event = make_event(
            extraction_changed="spec", previous_changed_at=datetime(2026, 4, 9, tzinfo=UTC)
        )
        ctx = build_template_context(event, ITEM)
        assert ctx["previous_fingerprint"] == PREVIOUS_FP
        assert ctx["current_fingerprint"] == CURRENT_FP
        assert ctx["extraction_changed"] == "spec"
        assert ctx["previous_changed_at"] == "2026-04-09T00:00:00Z"
        assert ctx["change_url"] == ITEM_PAGE

    def test_absent_values_are_empty_strings_not_none(self):
        """A lenient render shows ``None`` as the word; empty is what a reader expects."""
        ctx = build_template_context(make_event(), ItemFacts(name="n"))
        for name in ("extraction_changed", "previous_changed_at", "domain_name", "description"):
            assert ctx[name] == "", name
        assert build_template_context(make_event("watch_recovered"), ITEM)["error_since"] == ""

    def test_last_changed_at_is_this_change_or_empty(self):
        """Archiver has no item-level last change; on a change it is this one (Watcher #349)."""
        assert build_template_context(make_event(), ITEM)["last_changed_at"] == (
            "2026-04-14T12:00:00Z"
        )
        error = build_template_context(make_event("watch_error"), ITEM)
        assert error["last_changed_at"] == ""

    def test_error_variables(self):
        ctx = build_template_context(make_event("watch_error", status_code=503), ITEM)
        assert ctx["reason"] == "http_status"
        assert ctx["status_code"] == 503
        assert ctx["renotify"] is False
        assert ctx["previously_notified_at"] == ""

    def test_a_null_status_code_is_left_undefined(self):
        """So Watcher's ``status_code | default('unknown')`` still works."""
        ctx = build_template_context(make_event("watch_error", status_code=None), ITEM)
        assert "status_code" not in ctx

    def test_recovered_variables(self):
        event = make_event("watch_recovered", error_since=datetime(2026, 4, 1, tzinfo=UTC))
        assert build_template_context(event, ITEM)["error_since"] == "2026-04-01T00:00:00Z"

    def test_occurred_at_iso_preserves_microseconds(self):
        event = make_event(occurred_at=datetime(2026, 4, 23, 0, 38, 33, 123456, tzinfo=UTC))
        ctx = build_template_context(event, ITEM)
        assert ctx["occurred_at_iso"] == "2026-04-23T00:38:33.123456Z"

    def test_change_url_is_empty_without_a_base_or_off_a_change(self, monkeypatch):
        assert build_template_context(make_event("watch_error"), ITEM)["change_url"] == ""
        monkeypatch.delenv(PUBLIC_BASE_URL_ENV)
        ctx = build_template_context(make_event(), ITEM)
        assert ctx["change_url"] == ""
        assert ctx["app_url"] == ""

    def test_event_labels(self):
        for event_type in EVENTS:
            ctx = build_template_context(make_event(event_type), ITEM)
            assert ctx["event_label"] == EVENT_LABELS[event_type]


class TestBuildBodyWithTemplates:
    def test_body_template_overrides_default_body_and_toggles(self):
        opts = ContentOptions(include_domain=True, body_template="custom: {{ item_name }}")
        body = build_body(make_event(), FULL_ITEM, opts)
        assert body == "custom: Test Item"

    def test_change_url_available_in_custom_template(self):
        opts = ContentOptions(body_template="link: {{ change_url }}")
        assert build_body(make_event(), ITEM, opts) == f"link: {ITEM_PAGE}"

    def test_a_failing_custom_body_raises(self):
        with pytest.raises(ZeroDivisionError):
            build_body(make_event(), ITEM, ContentOptions(body_template="{{ 1 / 0 }}"))


class TestBuildTitle:
    def test_uses_the_default_for_every_event(self):
        """The ``[Watcher]`` prefix stays: recipients filter on it, and #369's shadow
        compares titles. Renaming it is the operator's call."""
        for event_type in EVENTS:
            title = build_title(make_event(event_type), ITEM, ContentOptions())
            assert title == f"[Watcher] {EVENT_LABELS[event_type]}: Test Item"

    def test_user_title_template_overrides_default(self):
        opts = ContentOptions(title_template="[{{ item_name }}] custom")
        assert build_title(make_event(), ITEM, opts) == "[Test Item] custom"

    def test_strict_raises_on_an_undefined_variable(self):
        opts = ContentOptions(title_template="{{ unknown_var }}")
        with pytest.raises(UndefinedError):
            build_title(make_event(), ITEM, opts, strict=True)


class TestCompose:
    """The send path (D2): a custom template that fails renders the event's default,
    and a WARNING names the subscription, never the template."""

    def test_composes_title_and_body(self):
        assert compose(make_event("watch_recovered"), ITEM, ContentOptions()) == Composed(
            title="[Watcher] Recovered: Test Item",
            body="https://example.com is responding normally again",
        )

    @pytest.mark.parametrize(
        "broken",
        ["{{ unclosed", "{{ ''.__class__.__mro__ }}", "{{ 1 / 0 }}", "{{ item_name.nope() }}"],
    )
    def test_a_failing_custom_template_sends_the_default(self, broken, caplog):
        # model_construct: the write path refuses a syntax error, but a send must
        # survive whatever a row holds.
        opts = ContentOptions.model_construct(title_template=broken, body_template=broken)
        with caplog.at_level(logging.WARNING):
            out = compose(make_event("watch_recovered"), ITEM, opts, subscription_id="SUB1")
        assert out == compose(make_event("watch_recovered"), ITEM, ContentOptions())
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert {r.field for r in warnings} == {"title", "body"}
        for record in warnings:
            assert record.subscription_id == "SUB1"
            assert broken not in record.getMessage()
            assert broken not in str(record.__dict__)

    def test_the_change_default_keeps_its_toggles(self):
        opts = ContentOptions(include_domain=True, body_template="{{ 1 / 0 }}")
        assert "- DOMAIN: example.com" in compose(make_event(), FULL_ITEM, opts).body

    def test_an_undefined_variable_renders_empty_at_send(self):
        """Lenient at send, as in Watcher: only a raised error falls back."""
        opts = ContentOptions(body_template="[{{ status_code }}]")
        assert compose(make_event(), ITEM, opts).body == "[]"


#: Two hunks: four lines, then two. Rendered, an empty line separates them.
DIFF = ChangeDiff(
    hunks=(
        ("  alpha", "- beta", "+ beta-changed", "  gamma delta"),
        ("  epsilon", "+ zeta"),
    )
)


def _long_diff(n: int = 30) -> ChangeDiff:
    return ChangeDiff(hunks=tuple((f"- old-{i}", f"+ new-{i}") for i in range(n)))


def _fenced(body: str) -> list[str]:
    """The diff block's lines, fences included."""
    return body.split("\n\n", 1)[1].split("\n")


class TestDiffSlot:
    def test_snippet_renders_after_the_list(self):
        listing, fenced = build_body(make_event(), ITEM, ContentOptions(), diff=DIFF).split(
            "\n\n", 1
        )
        assert all(line.startswith("- ") for line in listing.split("\n"))
        assert fenced.startswith("```diff\n")
        assert fenced.endswith("```")
        assert "- beta" in fenced
        assert "+ zeta" in fenced

    def test_hunks_are_separated_by_an_empty_line(self):
        lines = _fenced(build_body(make_event(), ITEM, ContentOptions(), diff=DIFF))
        assert lines[1:-1] == [*DIFF.hunks[0], "", *DIFF.hunks[1]]

    def test_snippet_is_capped_at_a_hunk_boundary(self):
        body = build_body(make_event(), ITEM, ContentOptions(diff_snippet_lines=6), diff=DIFF)
        assert "+ beta-changed" in body
        assert "+ zeta" not in body
        assert "... (2 more lines)" in body

    def test_cap_below_the_first_hunk_keeps_its_first_lines(self):
        body = build_body(make_event(), ITEM, ContentOptions(diff_snippet_lines=3), diff=DIFF)
        assert _fenced(body)[1:-1] == ["  alpha", "- beta", "... (4 more lines)"]

    def test_full_supersedes_the_snippet_cap(self):
        opts = ContentOptions(include_diff_full=True, diff_snippet_lines=1)
        body = build_body(make_event(), ITEM, opts, diff=DIFF)
        assert "+ zeta" in body
        assert "more line" not in body

    def test_omitted_when_both_toggles_off(self):
        opts = ContentOptions(include_diff_snippet=False)
        assert "```" not in build_body(make_event(), ITEM, opts, diff=DIFF)

    def test_omitted_when_no_diff_was_computed(self):
        body = build_body(make_event(), ITEM, ContentOptions(), diff=None)
        assert "```" not in body
        assert "DIFF" not in body

    def test_unavailable_is_said_as_a_list_item(self):
        body = build_body(
            make_event(), ITEM, ContentOptions(), diff=ChangeDiff(unavailable="content too large")
        )
        assert body.split("\n")[-1] == "- DIFF: unavailable (content too large)"
        assert "```" not in body

    def test_unavailable_is_silent_when_no_diff_was_asked_for(self):
        body = build_body(
            make_event(),
            ITEM,
            ContentOptions(include_diff_snippet=False),
            diff=ChangeDiff(unavailable="content too large"),
        )
        assert "DIFF" not in body

    def test_the_spec_note_stays_in_the_list_above_the_diff(self):
        event = make_event(extraction_changed="spec")
        listing, _ = build_body(event, ITEM, ContentOptions(), diff=DIFF).split("\n\n", 1)
        assert listing.split("\n")[-1] == f"- {SPEC_CHANGED_NOTE}"

    def test_non_change_events_never_carry_a_diff(self):
        event = make_event("watch_error", status_code=500)
        opts = ContentOptions(include_diff_full=True)
        assert "```" not in build_body(event, ITEM, opts, diff=DIFF)


class TestRenderedSizeBackstop:
    def _inner(self, body: str) -> str:
        return "\n".join(_fenced(body)[1:-1])

    def test_a_rewrite_is_cut_on_a_hunk_boundary(self):
        hunk = tuple(f"+ {'word ' * 12}{i}" for i in range(20))
        diff = ChangeDiff(hunks=(hunk,) * 100)
        body = build_body(make_event(), ITEM, ContentOptions(include_diff_full=True), diff=diff)
        inner = self._inner(body)
        assert len(inner.encode()) <= MAX_RENDERED_DIFF_BYTES
        kept = inner.split("\n... (")[0].split("\n")
        assert len([line for line in kept if line]) % len(hunk) == 0
        assert inner.endswith(" more lines)")

    def test_one_enormous_line_is_cut_within_the_line(self):
        diff = ChangeDiff(hunks=(("  before", "+ " + "é" * MAX_RENDERED_DIFF_BYTES),))
        body = build_body(make_event(), ITEM, ContentOptions(include_diff_full=True), diff=diff)
        inner = self._inner(body)
        assert len(inner.encode()) <= MAX_RENDERED_DIFF_BYTES
        assert inner.split("\n")[1].endswith("é…")

    def test_the_snippet_is_bounded_too(self):
        diff = ChangeDiff(hunks=(("+ " + "x" * 100_000,),))
        ctx = build_template_context(make_event(), ITEM, diff=diff)
        assert len(ctx["diff_snippet"].encode()) <= MAX_RENDERED_DIFF_BYTES + 64

    def test_the_fence_counts_against_the_cap(self):
        diff = ChangeDiff(hunks=(("+ " + "`" * 40_000,),))
        for options in (ContentOptions(), ContentOptions(include_diff_full=True)):
            block = build_body(make_event(), ITEM, options, diff=diff).split("\n\n", 1)[1]
            assert len(block.encode()) <= MAX_RENDERED_DIFF_BYTES
            lines = block.split("\n")
            assert lines[0] == f"{lines[-1]}diff"
            runs = re.findall(r"`+", "\n".join(lines[1:-1]))
            assert len(lines[-1]) > max(len(run) for run in runs)


class TestDiffFenceCannotBeClosedByContent:
    """The diff carries the watched page's text into a body Notifier renders as
    Markdown: the fence must outrun every backtick run in it (Watcher CR 13/14)."""

    HOSTILE = ChangeDiff(
        hunks=(("  ```", "  ![x](https://tracker.example/p.png)", "- old", "+ new"),)
    )

    @staticmethod
    def _closes(line: str, fence: str) -> bool:
        stripped = line.strip(" ")
        return (
            len(line) - len(line.lstrip(" ")) <= 3
            and stripped.startswith(fence)
            and set(stripped) == {"`"}
        )

    def test_a_content_line_cannot_close_the_fence(self):
        lines = _fenced(build_body(make_event(), ITEM, ContentOptions(), diff=self.HOSTILE))
        fence = lines[-1]
        assert lines[0] == f"{fence}diff"
        assert fence == "````"
        assert not any(self._closes(line, fence) for line in lines[1:-1])

    def test_a_hostile_page_stays_inside_the_fence_end_to_end(self):
        previous = (
            b"intro\n```\n![x](https://tracker.example/p.png)\n<script>alert(1)</script>\nold tail"
        )
        current = previous.replace(b"old tail", b"`````\n# heading\nnew tail")
        body = build_body(
            make_event(),
            ITEM,
            ContentOptions(include_diff_full=True),
            diff=compute_change_diff(previous, current),
        )
        lines = _fenced(body)
        fence = lines[-1]
        assert fence == "``````"
        inner = lines[1:-1]
        assert not any(self._closes(line, fence) for line in inner)
        assert "+ # heading" in inner

    def test_template_variables_use_the_same_fence(self):
        ctx = build_template_context(make_event(), ITEM, diff=self.HOSTILE)
        assert ctx["diff_full"].startswith("````diff\n")
        assert ctx["diff_snippet"].endswith("\n````")


class TestDiffTemplateVariables:
    def test_snippet_and_full_are_fenced(self):
        ctx = build_template_context(make_event(), ITEM, diff=DIFF)
        assert ctx["diff_snippet"].startswith("```diff\n")
        assert "+ zeta" in ctx["diff_full"]

    def test_snippet_capped_at_the_default_full_never(self):
        ctx = build_template_context(make_event(), ITEM, diff=_long_diff())
        assert "more line" in ctx["diff_snippet"]
        assert "more line" not in ctx["diff_full"]

    def test_empty_without_a_diff(self):
        ctx = build_template_context(make_event(), ITEM)
        assert ctx["diff_snippet"] == ctx["diff_full"] == ""

    def test_unavailable_says_why(self):
        ctx = build_template_context(
            make_event(), ITEM, diff=ChangeDiff(unavailable="previous text not stored")
        )
        assert ctx["diff_snippet"] == "(diff unavailable: previous text not stored)"

    def test_custom_template_honours_the_user_cap(self):
        opts = ContentOptions(body_template="{{ diff_snippet }}", diff_snippet_lines=4)
        assert "more line" in build_body(make_event(), ITEM, opts, diff=_long_diff())
        full = ContentOptions(body_template="{{ diff_full }}")
        assert "more line" not in build_body(make_event(), ITEM, full, diff=_long_diff())


class TestTruncateHunks:
    HUNKS = DIFF.hunks

    def test_fits_untouched(self):
        assert _truncate_hunks(self.HUNKS, max_lines=7, max_bytes=1000) == (
            [*self.HUNKS[0], "", *self.HUNKS[1]],
            0,
        )

    def test_whole_hunks_only(self):
        assert _truncate_hunks(self.HUNKS, max_lines=6, max_bytes=1000) == (
            list(self.HUNKS[0]),
            2,
        )

    def test_a_one_line_cap_keeps_only_the_footer(self):
        assert _truncate_hunks(self.HUNKS, max_lines=1, max_bytes=1000) == ([], 6)

    def test_bytes_bound_without_a_line_cap(self):
        hunks = (("+ " + "a" * 40,), ("+ " + "b" * 40,))
        assert _truncate_hunks(hunks, max_lines=None, max_bytes=80) == ([hunks[0][0]], 1)
