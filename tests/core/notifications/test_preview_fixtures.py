"""The preview's canned inputs (archiver#367, D5): one co-core event per kind, an item, a diff.

Watcher's fidelity invariant (#221), in Archiver's terms: the preview must show
no variable a real send lacks. Here the fixtures **are** co-core's event models,
built through the composer's own context, so the variables match by
construction. These tests hold the rest: every documented variable for an event
renders strict against its fixture, and the canned diff is the real algorithm's.
"""

import pytest
from co_core.pure.util.hashing import prefixed_sha256, sha256

from src.core.notifications.content import (
    build_body,
    build_title,
    render_template_strict,
)
from src.core.notifications.content_config import ContentOptions
from src.core.notifications.default_templates import EVENT_LABELS, TEMPLATE_VARIABLES
from src.core.notifications.diff import compute_change_diff
from src.core.notifications.preview_fixtures import (
    PREVIEW_CURRENT_TEXT,
    PREVIEW_ITEM,
    PREVIEW_PREVIOUS_TEXT,
    preview_diff,
    preview_event,
)

EVENTS = list(EVENT_LABELS)


@pytest.mark.parametrize("event_type", EVENTS)
def test_every_event_has_a_fixture_of_its_kind(event_type: str) -> None:
    assert preview_event(event_type).event_type == event_type


def test_an_unknown_event_is_a_key_error() -> None:
    with pytest.raises(KeyError):
        preview_event("watch_created")


def test_the_change_names_its_texts_by_their_digests() -> None:
    event = preview_event("change_detected")
    assert event.previous_fingerprint == prefixed_sha256(sha256(PREVIEW_PREVIOUS_TEXT))
    assert event.current_fingerprint == prefixed_sha256(sha256(PREVIEW_CURRENT_TEXT))


def test_the_canned_diff_is_the_real_algorithms() -> None:
    assert preview_diff("change_detected") == compute_change_diff(
        PREVIEW_PREVIOUS_TEXT, PREVIEW_CURRENT_TEXT
    )
    assert preview_diff("change_detected").hunks
    assert preview_diff("watch_error") is None


@pytest.mark.parametrize("event_type", EVENTS)
def test_every_documented_variable_renders_strict(event_type: str) -> None:
    """A template naming every variable for this event previews without an error."""
    names = [v.name for v in TEMPLATE_VARIABLES if v.scope in {"always", event_type}]
    source = " ".join(f"{{{{ {name} }}}}" for name in names)
    options = ContentOptions(title_template=source, body_template=source)
    event = preview_event(event_type)
    build_title(event, PREVIEW_ITEM, options, strict=True)
    build_body(event, PREVIEW_ITEM, options, strict=True, diff=preview_diff(event_type))


@pytest.mark.parametrize("event_type", EVENTS)
def test_the_defaults_render_strict(event_type: str) -> None:
    event = preview_event(event_type)
    assert build_title(event, PREVIEW_ITEM, ContentOptions(), strict=True)
    assert build_body(
        event, PREVIEW_ITEM, ContentOptions(), strict=True, diff=preview_diff(event_type)
    )


def test_a_variable_of_another_event_is_an_error_in_the_preview() -> None:
    with pytest.raises(Exception, match="status_code"):
        render_template_strict("{{ status_code }}", {})


def test_the_item_has_no_tags() -> None:
    """Fidelity: no item has tags until #362, so the preview shows none either."""
    assert PREVIEW_ITEM.tags == ()
