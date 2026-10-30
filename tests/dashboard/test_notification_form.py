"""The Notifications page's content form (archiver#363 D5, #367 D5). Pure.

Checkboxes post only when ticked, so the form carries every toggle and an
unticked one is ``False``. What is stored is the difference from the defaults,
so ``None`` stays "all defaults" and a later default change still applies.

**The Jinja fields are on the form since #367's preview** (D5), so the form is
the whole truth: a cleared field clears the template, and an override holding
one can be turned off. #363's carry-over went in the same change, or a cleared
field would silently keep the stored value. A template that doesn't parse is
refused by the validator the preview shares (``content_config``).
"""

from src.dashboard.notification_form import content_config_from_form, options_view, render_preview

_ALL_DEFAULT = {"default__include_diff_snippet": "on", "default__diff_snippet_lines": "25"}


def test_the_default_form_stores_none():
    assert content_config_from_form(_ALL_DEFAULT) == (None, [])


def test_an_unticked_box_is_false_and_only_differences_are_stored():
    form = {"default__diff_snippet_lines": "25", "default__include_domain": "on"}
    config, problems = content_config_from_form(form)
    assert problems == []
    assert config == {"default": {"include_diff_snippet": False, "include_domain": True}}


def test_an_override_is_stored_when_enabled_with_its_own_options():
    form = _ALL_DEFAULT | {
        "override__watch_error": "on",
        "watch_error__diff_snippet_lines": "10",
        "watch_error__include_diff_snippet": "on",
        "watch_recovered__include_domain": "on",  # its override is off: ignored
    }
    config, problems = content_config_from_form(form)
    assert problems == []
    assert config == {"overrides": {"watch_error": {"diff_snippet_lines": 10}}}


def test_an_enabled_override_left_at_defaults_is_kept_empty():
    form = _ALL_DEFAULT | {
        "override__change_detected": "on",
        "change_detected__include_diff_snippet": "on",
        "change_detected__diff_snippet_lines": "25",
    }
    assert content_config_from_form(form) == (
        {"overrides": {"change_detected": {}}},
        [],
    )


def test_templates_are_edited_on_the_form():
    form = _ALL_DEFAULT | {
        "default__title_template": "{{ item_name }}",
        "override__watch_error": "on",
        "watch_error__include_diff_snippet": "on",
        "watch_error__diff_snippet_lines": "25",
        "watch_error__body_template": "down: {{ item_name }}",
    }
    config, problems = content_config_from_form(form)
    assert problems == []
    assert config == {
        "default": {"title_template": "{{ item_name }}"},
        "overrides": {"watch_error": {"body_template": "down: {{ item_name }}"}},
    }


def test_a_cleared_field_clears_the_template():
    """No carry-over: an empty or blank field stores no template."""
    form = _ALL_DEFAULT | {"default__title_template": "", "default__body_template": "  \r\n "}
    assert content_config_from_form(form) == (None, [])


def test_an_override_holding_a_template_can_be_turned_off():
    form = _ALL_DEFAULT | {"watch_error__body_template": "down"}  # its override is off
    assert content_config_from_form(form) == (None, [])


def test_textarea_line_endings_are_stored_as_newlines():
    """Browsers post a textarea's newlines as CRLF."""
    form = _ALL_DEFAULT | {"default__body_template": "a\r\nb\r\n"}
    config, _ = content_config_from_form(form)
    assert config == {"default": {"body_template": "a\nb\n"}}


def test_a_template_that_does_not_parse_names_its_block_and_field():
    form = _ALL_DEFAULT | {
        "override__watch_error": "on",
        "watch_error__include_diff_snippet": "on",
        "watch_error__diff_snippet_lines": "25",
        "watch_error__body_template": "{{ unclosed",
    }
    config, problems = content_config_from_form(form)
    assert config is None
    assert len(problems) == 1
    assert problems[0].startswith("Error: body template: not a valid Jinja template")


def test_a_bad_snippet_length_is_a_problem():
    for raw in ("abc", "0", "201", ""):
        form = {"default__include_diff_snippet": "on", "default__diff_snippet_lines": raw}
        config, problems = content_config_from_form(form)
        assert config is None
        assert problems and "1-200" in problems[0], raw


def test_options_view_fills_defaults_and_marks_overrides():
    view = options_view({"default": {"include_domain": True}, "overrides": {"watch_error": {}}})
    assert view["default"]["include_domain"] is True
    assert view["default"]["include_diff_snippet"] is True
    assert view["default"]["diff_snippet_lines"] == 25
    assert view["default"]["title_template"] is None
    assert view["overrides"]["watch_error"]["include_diff_snippet"] is True
    assert view["overrides"]["change_detected"] is None


def test_options_view_carries_the_templates_for_the_fields():
    view = options_view({"overrides": {"watch_error": {"title_template": "x"}}})
    assert view["overrides"]["watch_error"]["title_template"] == "x"


# --- render_preview (archiver#367, D5) --------------------------------------


def test_the_preview_renders_the_default_against_the_fixture():
    view = render_preview(_ALL_DEFAULT, "change_detected")
    assert view["errors"] == []
    assert view["block"] == "default"
    assert view["title"] == "[Watcher] Change: Example item"
    assert view["body"].startswith("- Example item\n- URL: https://example.com/regulatory-page")
    assert "```diff" in view["body"]


def test_the_preview_uses_the_events_override_when_on():
    form = _ALL_DEFAULT | {
        "override__watch_error": "on",
        "watch_error__diff_snippet_lines": "25",
        "watch_error__title_template": "down: {{ item_name }} ({{ status_code }})",
    }
    view = render_preview(form, "watch_error")
    assert view["block"] == "override"
    assert view["title"] == "down: Example item (503)"


def test_a_syntax_error_shows_as_on_save():
    form = _ALL_DEFAULT | {"default__body_template": "{% if %}"}
    view = render_preview(form, "watch_recovered")
    assert view["body"] is None
    assert view["errors"] == content_config_from_form(form)[1]


def test_an_undefined_variable_shows_in_the_preview_but_saves():
    """A default-block body may name a variable only some events define."""
    form = _ALL_DEFAULT | {"default__body_template": "HTTP {{ status_code }}"}
    view = render_preview(form, "change_detected")
    assert view["errors"] == ["Body: UndefinedError: 'status_code' is undefined"]
    assert view["title"] == "[Watcher] Change: Example item"
    assert render_preview(form, "watch_error")["body"] == "HTTP 503"
    assert content_config_from_form(form)[1] == []


def test_the_sandbox_refusal_shows():
    form = _ALL_DEFAULT | {"default__title_template": "{{ ''.__class__.__mro__ }}"}
    view = render_preview(form, "change_detected")
    assert view["title"] is None
    assert view["errors"] and view["errors"][0].startswith("Title: ")


def test_an_unknown_event_previews_the_first():
    assert render_preview(_ALL_DEFAULT, "nope")["event"] == "change_detected"
