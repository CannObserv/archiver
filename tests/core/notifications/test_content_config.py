"""ContentConfig: Watcher's content options, validated stricter at write time (#363, D4).

Watcher ignores unknown keys and checks nothing about a Jinja template until it
renders one. Here an unknown key is refused, an override must name a known
event, ``diff_snippet_lines`` is 1-200, and a template must parse in Jinja's
sandbox. Only syntax: the render context is #367's to define.
"""

import pytest
from pydantic import ValidationError

from src.core.notifications.content_config import (
    RETIRED_CONTENT_KEYS,
    ContentConfig,
    normalize_content_config,
)


def _locs(exc: ValidationError) -> list[tuple]:
    return [e["loc"] for e in exc.errors()]


def test_empty_config_is_all_watcher_defaults():
    config = ContentConfig.model_validate({})
    assert config.default.include_diff_snippet is True
    assert config.default.diff_snippet_lines == 25
    assert config.default.include_diff_full is False
    for flag in (
        "include_temporal_context",
        "include_domain",
        "include_last_changed_at",
        "include_tags",
        "include_description",
    ):
        assert getattr(config.default, flag) is False
    assert config.default.title_template is None
    assert config.default.body_template is None
    assert config.overrides == {}


def test_overrides_keyed_by_known_events_validate():
    config = ContentConfig.model_validate(
        {"overrides": {"watch_error": {"include_diff_snippet": False}}}
    )
    assert config.overrides["watch_error"].include_diff_snippet is False


def test_an_override_on_an_unknown_event_is_refused():
    with pytest.raises(ValidationError) as caught:
        ContentConfig.model_validate({"overrides": {"digest": {}}})
    assert ("overrides", "digest", "[key]") in _locs(caught.value)


@pytest.mark.parametrize("where", ["top", "default", "override"])
def test_unknown_keys_are_refused_at_every_level(where):
    doc = {
        "top": {"surprise": 1},
        "default": {"default": {"include_significance": True}},
        "override": {"overrides": {"change_detected": {"nope": True}}},
    }[where]
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ContentConfig.model_validate(doc)


def test_the_retired_keys_are_named_for_the_importer():
    assert RETIRED_CONTENT_KEYS == frozenset(
        {"include_significance", "include_change_dashboard_url"}
    )


@pytest.mark.parametrize("lines", [0, 201, -1])
def test_diff_snippet_lines_is_bounded(lines):
    with pytest.raises(ValidationError) as caught:
        ContentConfig.model_validate({"default": {"diff_snippet_lines": lines}})
    assert ("default", "diff_snippet_lines") in _locs(caught.value)


@pytest.mark.parametrize("lines", [1, 200])
def test_diff_snippet_lines_bounds_are_inclusive(lines):
    config = ContentConfig.model_validate({"default": {"diff_snippet_lines": lines}})
    assert config.default.diff_snippet_lines == lines


def test_toggles_are_strict_booleans():
    with pytest.raises(ValidationError):
        ContentConfig.model_validate({"default": {"include_domain": "yes"}})


def test_a_template_that_parses_is_kept_verbatim():
    src = "{{ item_name }} changed{% if event_type == 'watch_error' %}!{% endif %}"
    config = ContentConfig.model_validate({"default": {"title_template": src}})
    assert config.default.title_template == src


@pytest.mark.parametrize("field", ["title_template", "body_template"])
def test_a_template_that_does_not_parse_is_refused_naming_the_field(field):
    with pytest.raises(ValidationError) as caught:
        ContentConfig.model_validate({"overrides": {"watch_error": {field: "{% if %}"}}})
    errors = caught.value.errors()
    assert errors[0]["loc"] == ("overrides", "watch_error", field)
    assert "Jinja" in errors[0]["msg"]
    assert "line 1" in errors[0]["msg"]


def test_an_unclosed_block_is_refused():
    with pytest.raises(ValidationError, match="Jinja"):
        ContentConfig.model_validate({"default": {"body_template": "{% for x in y %}"}})


def test_a_template_is_parsed_not_rendered():
    """An attribute walk parses; the sandbox refuses it at render time (#367)."""
    src = "{{ ''.__class__.__mro__ }}"
    config = ContentConfig.model_validate({"default": {"body_template": src}})
    assert config.default.body_template == src


def test_normalize_fills_defaults_so_equal_intent_compares_equal():
    assert normalize_content_config(None) == normalize_content_config({})
    assert normalize_content_config({"default": {"include_diff_snippet": True}}) == (
        normalize_content_config(None)
    )
    assert normalize_content_config({"default": {"include_domain": True}}) != (
        normalize_content_config(None)
    )
