"""Destination rendering — the value Replicator receives (archiver#168).

Archiver renders; Replicator never interpolates. So every failure these tests
describe is one Archiver must catch locally, before the command is published:
the async alternative is a ``ReplicationFailedEvent`` on a service that cannot
fix it.
"""

from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from co_core.pure.util.files import extension_for_media_type

from src.core.replication import destination
from src.core.replication.destination import (
    DestinationCollisionError,
    DestinationRenderError,
    InvalidFieldValueError,
    InvalidOccasionError,
    MissingFieldError,
    RenderOccasion,
    UnsafeDestinationError,
    assert_distinct_destinations,
    extension_for,
    find_collisions,
    probe_destination,
    render_destination,
)
from src.core.replication.errors import ReplicationRenderError
from tests.core.replication._import_scan import assigned_names, imported_modules

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


def test_find_collisions_reports_every_group_not_just_the_first():
    """The issuance path decides what to skip from this, so a partial answer
    would silence assignments that do not collide (CR #12)."""
    groups = find_collisions({"a": "x", "b": "x", "c": "unique", "d": "y", "e": "y"})

    assert groups == {"x": ["a", "b"], "y": ["d", "e"]}


def test_find_collisions_is_empty_when_every_destination_is_distinct():
    assert find_collisions({"a": "x", "b": "y"}) == {}


def test_colliding_destinations_refused_with_both_assignments_named():
    """Two active assignments rendering one path would return as
    destination_conflict — a conflict token for a path-design error."""
    with pytest.raises(DestinationCollisionError) as exc:
        assert_distinct_destinations({"assignment-a": "same/key", "assignment-b": "same/key"})
    assert "assignment-a" in str(exc.value)
    assert "assignment-b" in str(exc.value)


# --- the occasion keys added for the canonical organizations/ layout (archiver#205) ---


def test_year_and_segments_render_in_the_storage_framework_forms():
    """``_DateProps`` spellings, byte for byte: ``%Y``, ``%Y_%m_%d``, ``%Y_%m_%d-%H_%M_%S``."""
    rendered = render_destination(
        "{source_revision.year}/{source_revision.date_segment}/"
        "{source_revision.datetime_time_segment}/{source_revision.id}",
        rep_fields={},
        occasion=_occasion(captured_at=datetime(2026, 8, 17, 14, 30, 5, tzinfo=UTC)),
    )
    assert rendered == "2026/2026_08_17/2026_08_17-14_30_05/01JZZZZZZZZZZZZZZZZZZZZZZZ"


def test_segments_render_in_utc_whatever_zone_the_row_carries():
    rendered = render_destination(
        "{source_revision.datetime_time_segment}/{source_revision.id}",
        rep_fields={},
        occasion=_occasion(
            captured_at=datetime(2026, 8, 17, 16, 30, 5, tzinfo=timezone(timedelta(hours=2)))
        ),
    )
    assert rendered.startswith("2026_08_17-14_30_05/")


@pytest.mark.parametrize(
    ("media_type", "ext"),
    [
        ("text/html", "html"),
        ("text/html; charset=utf-8", "html"),
        ("TEXT/HTML", "html"),
        ("application/pdf", "pdf"),
        ("application/json", "json"),
        ("text/plain", "txt"),
        ("text/csv", "csv"),
        ("image/png", "png"),
        ("application/octet-stream", "bin"),
        ("application/x-nobody-registered-this", "bin"),
        (None, "bin"),
        # Off the shared table (archiver#210). Each of these resolved through
        # ``mimetypes`` before the delegation - ``mp3``, ``mp4``, ``webp`` - and
        # ``image/webp`` resolved only on a host whose mime files list it. The
        # key is permanent and citable, so it may depend on neither.
        ("audio/mpeg", "bin"),
        ("video/mp4", "bin"),
        ("image/webp", "bin"),
        ("text/markdown", "bin"),
    ],
)
def test_ext_derives_from_the_source_media_type(media_type, ext):
    """What the origin served decides the extension; unknown is ``bin``, never a guess."""
    rendered = render_destination(
        "{source_revision.id}.{source_revision.ext}",
        rep_fields={},
        occasion=_occasion(source_media_type=media_type),
    )
    assert rendered == f"01JZZZZZZZZZZZZZZZZZZZZZZZ.{ext}"


# Everything the delegation is checked over: the table's own entries, the forms
# that exercise parameter-stripping and case-folding, the types that used to
# resolve through ``mimetypes``, and the three that must answer ``bin``.
_MEDIA_TYPES_CHECKED = (
    "text/html",
    "text/html; charset=utf-8",
    "TEXT/HTML",
    "application/xhtml+xml",
    "application/pdf",
    "application/json",
    "application/xml",
    "text/xml",
    "text/plain",
    "text/csv",
    "image/png",
    "image/jpeg",
    "image/gif",
    "application/octet-stream",
    "audio/mpeg",
    "video/mp4",
    "image/webp",
    "application/zip",
    "image/svg+xml",
    "application/msword",
    "text/markdown",
    "application/x-nobody-registered-this",
    "",
    None,
)


def test_extension_for_is_co_cores_table_and_not_a_second_copy():
    """``extension_for`` delegates and adds nothing (archiver#210).

    Not a cross-table agreement check: after the delegation there is one table,
    so the equality below holds by construction and can only break if a local
    branch, override or normalisation step is reintroduced ahead of the call.
    That is the regression this guards, and it is the whole of it — the drift
    the issue was filed about is prevented by there being nothing left here to
    drift, not by this assertion.

    The cluster keeps one media-type table as it keeps one slugger: the storage
    framework renders ``{source_revision.ext}`` from ``extension_for_media_type``
    too, so any local adjustment would be a key archiver writes and the
    framework cannot find.
    """
    for media_type in _MEDIA_TYPES_CHECKED:
        assert extension_for(media_type) == extension_for_media_type(media_type), media_type


def test_every_extension_co_core_yields_is_a_usable_path_segment():
    """The charset claim in ``extension_for``'s docstring, pinned (archiver#210 CR 2).

    ``_EXTENSION_SAFE`` used to enforce this locally and was deleted with the
    table, so the property is now a fact about another repository's data that
    this one depends on. ``RenderOccasion.values`` re-checks every occasion
    value, so an unsafe answer raises rather than writing a malformed key — but
    it would raise at replication time, pointing at a table this repo does not
    own. Checking it here names the owner before a command is ever issued.
    """
    for media_type in _MEDIA_TYPES_CHECKED:
        ext = extension_for(media_type)
        assert destination._SEGMENT_SAFE.match(ext), (media_type, ext)
        assert ext not in destination._REFUSED_SEGMENTS, (media_type, ext)


def test_no_local_extension_table_survives():
    """The delegation removed the table, the fallback and the ``mimetypes`` import.

    A structural assertion because the behavioural ones above cannot see a table
    that is still present but shadowed - and a resurrected local table would
    re-open the split silently, on whichever media types someone added to it.

    Parsed rather than grepped (CR 3). ``"import mimetypes" not in source``
    read past ``from mimetypes import guess_extension`` and
    ``import mimetypes as mt`` — the two spellings most likely to appear if the
    fallback comes back — and tripped on any prose containing the phrase, which
    this module's own comment block already runs close to. ``_imported_modules``
    is the layering guard's scanner, which its own planted-import tests keep
    honest, so the detector is proven elsewhere rather than trusted here.
    """
    module = Path(destination.__file__)
    assert "mimetypes" not in imported_modules(module)
    assert "_EXTENSIONS" not in assigned_names(module)
    assert not hasattr(destination, "_EXTENSIONS")


def test_the_mimetypes_guard_fires_on_each_spelling(tmp_path):
    """The three forms the substring check could not all see."""
    for source in (
        "import mimetypes\n",
        "import mimetypes as mt\n",
        "from mimetypes import guess_extension\n",
    ):
        planted = tmp_path / "planted.py"
        planted.write_text(source)
        assert "mimetypes" in imported_modules(planted), source


# --- bag slugs derive at render time with the shared normalizer (archiver#206) ---


def test_bag_slugs_derive_at_render_time_with_the_shared_normalizer():
    """``org.title_slug`` comes from ``org.title`` via co-core's ``normalize_string``,
    so a segment archiver renders matches the one the storage framework renders."""
    rendered = render_destination(
        "{org.title_slug}/{info_item.name_slug}/{source_revision.id}",
        rep_fields={
            "org": {"title": "WSLCB - Meeting Schedule"},
            "info_item": {"name": "Café Résumé"},
        },
        occasion=_occasion(),
    )
    assert rendered == "wslcb-meeting_schedule/cafe_resume/01JZZZZZZZZZZZZZZZZZZZZZZZ"


def test_a_stored_slug_is_an_explicit_override():
    rendered = render_destination(
        "{org.title_slug}/{source_revision.id}",
        rep_fields={"org": {"title": "Anything At All", "title_slug": "custom"}},
        occasion=_occasion(),
    )
    assert rendered == "custom/01JZZZZZZZZZZZZZZZZZZZZZZZ"


def test_a_raw_placeholder_still_refuses_rather_than_rewrites():
    """Resolution adds ``_slug`` companions; it never slugifies a raw placeholder."""
    with pytest.raises(InvalidFieldValueError):
        render_destination(
            "{org.title}/{source_revision.id}",
            rep_fields={"org": {"title": "WA LCB"}},
            occasion=_occasion(),
        )


def test_probe_resolves_slugs_the_same_way():
    probe_destination(
        {"path_template": "{org.title_slug}/{source_revision.id}"},
        {"org": {"title": "Washington State LCB"}},
    )


# --- the golden rendering the epic was approved on (archiver#207) ---

CANONICAL_LAYOUT = (
    "organizations/{org.title_slug}/infoitems/{info_item.name_slug}/{source_revision.year}/"
    "{source_revision.datetime_time_segment}-{info_item.name_slug}-{source_revision.id}"
    ".{source_revision.ext}"
)


def test_the_canonical_layout_renders_the_approved_key():
    rendered = render_destination(
        CANONICAL_LAYOUT,
        rep_fields={
            "org": {"title": "Washington State Liquor and Cannabis Board", "acronym": "WSLCB"},
            "info_item": {"name": "Public Hearings and Outreach"},
        },
        occasion=RenderOccasion(
            source_revision_id="01M23RDZKZS6FSPP1YZFBEQB2R",
            content_fingerprint=FINGERPRINT,
            captured_at=datetime(2026, 9, 9, 18, 54, 2, tzinfo=UTC),
            source_media_type="text/html",
        ),
    )
    assert rendered == (
        "organizations/washington_state_liquor_and_cannabis_board/infoitems/"
        "public_hearings_and_outreach/2026/"
        "2026_09_09-18_54_02-public_hearings_and_outreach-01M23RDZKZS6FSPP1YZFBEQB2R.html"
    )
