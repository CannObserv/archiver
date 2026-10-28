"""The Notifications page's content form (archiver#363, D5). Pure.

Checkboxes post only when ticked, so the form carries every toggle and an
unticked one is ``False``. What is stored is the difference from the defaults,
so ``None`` stays "all defaults" and a later default change still applies.

The Jinja fields are API-only until #367's preview (D5), and the form never
shows them - so an edit **carries the stored templates over**, and refuses to
drop an override that holds one, rather than erasing it silently.
"""

from src.dashboard.notification_form import content_config_from_form, options_view

_ALL_DEFAULT = {"default__include_diff_snippet": "on", "default__diff_snippet_lines": "25"}


def test_the_default_form_stores_none():
    assert content_config_from_form(_ALL_DEFAULT, None) == (None, [])


def test_an_unticked_box_is_false_and_only_differences_are_stored():
    form = {"default__diff_snippet_lines": "25", "default__include_domain": "on"}
    config, problems = content_config_from_form(form, None)
    assert problems == []
    assert config == {"default": {"include_diff_snippet": False, "include_domain": True}}


def test_an_override_is_stored_when_enabled_with_its_own_options():
    form = _ALL_DEFAULT | {
        "override__watch_error": "on",
        "watch_error__diff_snippet_lines": "10",
        "watch_error__include_diff_snippet": "on",
        "watch_recovered__include_domain": "on",  # its override is off: ignored
    }
    config, problems = content_config_from_form(form, None)
    assert problems == []
    assert config == {"overrides": {"watch_error": {"diff_snippet_lines": 10}}}


def test_an_enabled_override_left_at_defaults_is_kept_empty():
    form = _ALL_DEFAULT | {
        "override__change_detected": "on",
        "change_detected__include_diff_snippet": "on",
        "change_detected__diff_snippet_lines": "25",
    }
    assert content_config_from_form(form, None) == (
        {"overrides": {"change_detected": {}}},
        [],
    )


def test_stored_templates_are_carried_over():
    stored = {
        "default": {"title_template": "{{ item_name }}", "include_tags": True},
        "overrides": {"watch_error": {"body_template": "down: {{ item_name }}"}},
    }
    form = _ALL_DEFAULT | {
        "override__watch_error": "on",
        "watch_error__include_diff_snippet": "on",
        "watch_error__diff_snippet_lines": "25",
    }
    config, problems = content_config_from_form(form, stored)
    assert problems == []
    assert config == {
        "default": {"title_template": "{{ item_name }}"},
        "overrides": {"watch_error": {"body_template": "down: {{ item_name }}"}},
    }


def test_turning_off_an_override_that_holds_a_template_is_refused():
    stored = {"overrides": {"watch_error": {"body_template": "down"}}}
    config, problems = content_config_from_form(_ALL_DEFAULT, stored)
    assert config is None
    assert problems == [
        "the Error override holds a Jinja template set through the API; "
        "change or remove it through the API"
    ]


def test_a_bad_snippet_length_is_a_problem():
    for raw in ("abc", "0", "201", ""):
        form = {"default__include_diff_snippet": "on", "default__diff_snippet_lines": raw}
        config, problems = content_config_from_form(form, None)
        assert config is None
        assert problems and "1-200" in problems[0], raw


def test_options_view_fills_defaults_and_marks_overrides():
    view = options_view({"default": {"include_domain": True}, "overrides": {"watch_error": {}}})
    assert view["default"]["include_domain"] is True
    assert view["default"]["include_diff_snippet"] is True
    assert view["default"]["diff_snippet_lines"] == 25
    assert view["overrides"]["watch_error"]["include_diff_snippet"] is True
    assert view["overrides"]["change_detected"] is None
    assert view["templates"] is False


def test_options_view_says_when_a_template_is_set():
    assert options_view({"overrides": {"watch_error": {"title_template": "x"}}})["templates"]
    assert options_view(None)["templates"] is False
