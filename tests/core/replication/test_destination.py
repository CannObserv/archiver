"""Destination rendering — the value Replicator receives (archiver#168).

Archiver renders; Replicator never interpolates. So every failure these tests
describe is one Archiver must catch locally, before the command is published:
the async alternative is a ``ReplicationFailedEvent`` on a service that cannot
fix it.
"""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from src.core.replication.destination import (
    DestinationCollisionError,
    DestinationRenderError,
    InvalidFieldValueError,
    InvalidOccasionError,
    MissingFieldError,
    RenderOccasion,
    UnsafeDestinationError,
    assert_distinct_destinations,
    probe_destination,
    render_destination,
)
from src.core.replication.errors import ReplicationRenderError

FINGERPRINT = "sha256:" + "ab" * 32


def _occasion(**overrides) -> RenderOccasion:
    values = {
        "source_revision_id": "01JZZZZZZZZZZZZZZZZZZZZZZZ",
        "content_fingerprint": FINGERPRINT,
        "captured_at": datetime(2026, 8, 17, 14, 30, 5, tzinfo=UTC),
    }
    values.update(overrides)
    return RenderOccasion(**values)


# --- resolution ---


def test_renders_bag_and_occasion_values():
    rendered = render_destination(
        "archive/{info_item.slug}/{source_revision.fingerprint}.html",
        rep_fields={"info_item": {"slug": "wa-lcb-notices"}},
        occasion=_occasion(),
    )
    assert rendered == f"archive/wa-lcb-notices/{'ab' * 32}.html"


def test_fingerprint_renders_without_the_algorithm_prefix():
    """'sha256:' would put a colon in a path segment; the digest alone is safe."""
    rendered = render_destination(
        "{source_revision.fingerprint}", rep_fields={}, occasion=_occasion()
    )
    assert rendered == "ab" * 32


def test_date_renders_as_iso_calendar_date():
    rendered = render_destination(
        "{source_revision.date}/{source_revision.id}", rep_fields={}, occasion=_occasion()
    )
    assert rendered.startswith("2026-08-17/")


def test_captured_at_renders_in_basic_iso_form():
    """Extended ISO carries colons; the basic form is the path-safe spelling."""
    rendered = render_destination(
        "{source_revision.captured_at}/{source_revision.id}", rep_fields={}, occasion=_occasion()
    )
    assert rendered.startswith("20260817T143005Z/")


def test_numeric_and_boolean_bag_values_render():
    rendered = render_destination(
        "{event.year}/{doc.final}/{source_revision.id}",
        rep_fields={"event": {"year": 2026}, "doc": {"final": True}},
        occasion=_occasion(),
    )
    assert rendered.startswith("2026/true/")


def test_same_occasion_renders_the_same_key_twice():
    """R2/T4: a redelivery must target the same key for the no-op path to be safe."""
    args = {
        "rep_fields": {"info_item": {"slug": "wa-lcb-notices"}},
        "occasion": _occasion(),
    }
    template = "archive/{info_item.slug}/{source_revision.fingerprint}.html"
    assert render_destination(template, **args) == render_destination(template, **args)


def test_occasion_value_wins_over_a_bag_namespace_of_the_same_name():
    """A bag cannot shadow the occasion — the reserved namespace is reserved."""
    rendered = render_destination(
        "{source_revision.date}/{source_revision.id}",
        rep_fields={"source_revision": {"date": "1999-01-01"}},
        occasion=_occasion(),
    )
    assert rendered.startswith("2026-08-17/")


# --- unrenderable ---


def test_missing_bag_value_is_unrenderable():
    """rep_fields is editable after assignment, so required_fields is not a guarantee."""
    with pytest.raises(MissingFieldError):
        render_destination(
            "{info_item.slug}/{source_revision.id}", rep_fields={}, occasion=_occasion()
        )


def test_null_bag_value_is_unrenderable():
    with pytest.raises(MissingFieldError):
        render_destination(
            "{info_item.slug}/{source_revision.id}",
            rep_fields={"info_item": {"slug": None}},
            occasion=_occasion(),
        )


def test_empty_bag_value_is_unrenderable():
    with pytest.raises(InvalidFieldValueError):
        render_destination(
            "{info_item.slug}/{source_revision.id}",
            rep_fields={"info_item": {"slug": ""}},
            occasion=_occasion(),
        )


@pytest.mark.parametrize(
    "value",
    ["wa/lcb", "..", "wa lcb", "wa:lcb", "wa\\lcb", "wa%2flcb", "wa\x00lcb"],
)
def test_bag_value_outside_the_segment_charset_is_refused(value):
    """Refused, not rewritten: a rewrite changes a citable URL, and two distinct
    values that sanitize to one path collide."""
    with pytest.raises(InvalidFieldValueError):
        render_destination(
            "{info_item.slug}/{source_revision.id}",
            rep_fields={"info_item": {"slug": value}},
            occasion=_occasion(),
        )


# --- guards on the rendered string (issuer contract T3) ---


@pytest.mark.parametrize(
    "template",
    [
        "/archive/{source_revision.id}",  # absolute
        "archive/{source_revision.id}/",  # trailing separator
        "archive//{source_revision.id}",  # empty segment
        "archive/../{source_revision.id}",  # traversal
        "archive/./{source_revision.id}",  # non-normalized
        "C:/archive/{source_revision.id}",  # drive qualifier
        "archive\\{source_revision.id}",  # backslash
        "archive/%2e%2e/{source_revision.id}",  # traversal after percent-decoding
        "archive/ spaced/{source_revision.id}",  # untrimmed segment
    ],
)
def test_unsafe_rendered_path_refused(template):
    with pytest.raises(UnsafeDestinationError):
        render_destination(template, rep_fields={}, occasion=_occasion())


def test_plain_relative_path_is_safe():
    assert render_destination(
        "archive/2026/{source_revision.id}.html", rep_fields={}, occasion=_occasion()
    ).endswith(".html")


# --- the occasion is checked too (CR #2, #3) ---


@pytest.mark.parametrize("value", ["a/b", "..", "a b", "x\\y", "a:b", ""])
def test_occasion_value_outside_the_segment_charset_refused(value):
    """Half the vocabulary skipping the charset check is half a guard."""
    with pytest.raises(InvalidOccasionError):
        render_destination(
            "x/{source_revision.id}", rep_fields={}, occasion=_occasion(source_revision_id=value)
        )


def test_naive_captured_at_refused():
    """astimezone() on a naive value assumes VM-local and then stamps 'Z' on it —
    a wrong timestamp inside a permanent, citable path."""
    with pytest.raises(InvalidOccasionError):
        render_destination(
            "{source_revision.captured_at}/{source_revision.id}",
            rep_fields={},
            occasion=_occasion(captured_at=datetime(2026, 8, 17, 1, 30)),
        )


def test_non_utc_captured_at_is_converted_not_refused():
    """An aware value in another zone is unambiguous; only naive is refused."""
    rendered = render_destination(
        "{source_revision.date}/{source_revision.id}",
        rep_fields={},
        occasion=_occasion(
            captured_at=datetime(2026, 8, 17, 1, 30, tzinfo=timezone(timedelta(hours=4)))
        ),
    )
    assert rendered.startswith("2026-08-16/")


def test_render_errors_share_one_base():
    """archiver#169 catches one hierarchy to record a skip."""
    assert issubclass(DestinationRenderError, ReplicationRenderError)


# --- assignment-time pre-flight (CR #5) ---


def test_probe_accepts_a_renderable_document():
    probe_destination(
        {"path_template": "archive/{info_item.slug}/{source_revision.id}.html"},
        rep_fields={"info_item": {"slug": "wa-lcb-notices"}},
    )


def test_probe_refuses_a_bag_value_that_cannot_be_a_segment():
    """Present and non-null satisfies required_fields; it does not make a path."""
    with pytest.raises(InvalidFieldValueError):
        probe_destination(
            {"path_template": "archive/{org.name}/{source_revision.id}.html"},
            rep_fields={"org": {"name": "WA LCB"}},
        )


def test_probe_refuses_a_missing_bag_value():
    with pytest.raises(MissingFieldError):
        probe_destination(
            {"path_template": "archive/{org.name}/{source_revision.id}.html"}, rep_fields={}
        )


def test_probe_is_a_no_op_without_a_path_template():
    """Document validity is create-time's job; a partial document is not this
    check's failure to report."""
    probe_destination({"required_fields": []}, rep_fields={})


# --- fan-out pre-flight ---


def test_distinct_destinations_pass():
    assert_distinct_destinations({"assignment-a": "a/x", "assignment-b": "b/x"})


def test_colliding_destinations_refused_with_both_assignments_named():
    """Two active assignments rendering one path would return as
    destination_conflict — a conflict token for a path-design error."""
    with pytest.raises(DestinationCollisionError) as exc:
        assert_distinct_destinations({"assignment-a": "same/key", "assignment-b": "same/key"})
    assert "assignment-a" in str(exc.value)
    assert "assignment-b" in str(exc.value)
