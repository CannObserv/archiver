"""Destination rendering — the value Replicator receives (archiver#168).

Archiver renders; Replicator never interpolates. So every failure these tests
describe is one Archiver must catch locally, before the command is published:
the async alternative is a ``ReplicationFailedEvent`` on a service that cannot
fix it.
"""

from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from co_core.pure.storage import (
    FileVars,
    InformationItemVars,
    OrgVars,
    SourceRevisionVars,
    StorageConfig,
    StorageContext,
    StorageLocationKey,
    StorageProvider,
)
from co_core.pure.util.files import (
    _FALLBACK_MEDIA_EXTENSION,
    _MEDIA_TYPE_EXTENSIONS,
    extension_for_media_type,
)

from src.core.rep_fields import OrgValues, effective_rep_fields
from src.core.replication import destination
from src.core.replication.destination import (
    EXAMPLE_REVISION_ID,
    DestinationCollisionError,
    DestinationRenderError,
    InvalidFieldValueError,
    InvalidOccasionError,
    MissingFieldError,
    RenderOccasion,
    UnsafeDestinationError,
    assert_distinct_destinations,
    example_occasion,
    find_collisions,
    probe_destination,
    render_destination,
)
from src.core.replication.errors import ReplicationRenderError
from src.core.replication.template import MalformedTemplateError
from tests.core._import_scan import assigned_names, imported_modules

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


def test_renders_from_the_effective_bag():
    """archiver#303: the linked org's name reaches the path; a stored key still wins."""
    org = OrgValues(name="WA LCB", acronym="WSLCB")
    template = "organizations/{org.acronym_or_title_slug}/{org.title_slug}/{source_revision.id}"
    rendered = render_destination(template, rep_fields={}, occasion=_occasion(), org=org)
    assert rendered == "organizations/wslcb/wa_lcb/01JZZZZZZZZZZZZZZZZZZZZZZZ"
    stored = {"org": {"title": "Board"}}
    rendered = render_destination(template, rep_fields=stored, occasion=_occasion(), org=org)
    assert rendered == "organizations/wslcb/board/01JZZZZZZZZZZZZZZZZZZZZZZZ"


def test_probe_renders_from_the_effective_bag():
    document = {"path_template": "organizations/{org.title_slug}/{source_revision.id}"}
    path = probe_destination(document, {}, org=OrgValues(name="WA LCB", acronym=None))
    assert path is not None and path.startswith("organizations/wa_lcb/")


def test_renders_bag_and_occasion_values():
    rendered = render_destination(
        "archive/{info_item.slug}/{source_revision.fingerprint}.html",
        rep_fields={"info_item": {"slug": "wa-lcb-notices"}},
        occasion=_occasion(),
        org=None,
    )
    assert rendered == f"archive/wa-lcb-notices/{'ab' * 32}.html"


def test_fingerprint_renders_without_the_algorithm_prefix():
    """'sha256:' would put a colon in a path segment; the digest alone is safe."""
    rendered = render_destination(
        "{source_revision.fingerprint}", rep_fields={}, occasion=_occasion(), org=None
    )
    assert rendered == "ab" * 32


def test_date_label_renders_as_iso_calendar_date():
    rendered = render_destination(
        "{source_revision.date_label}/{source_revision.id}",
        rep_fields={},
        occasion=_occasion(),
        org=None,
    )
    assert rendered.startswith("2026-08-17/")


@pytest.mark.parametrize(
    "captured_at",
    [
        datetime(2026, 8, 17, 14, 30, 5, tzinfo=UTC),
        datetime(2026, 8, 17, 0, 0, 0, tzinfo=UTC),
        datetime(2026, 12, 31, 23, 59, 59, 999999, tzinfo=UTC),
        datetime(2026, 8, 17, 1, 30, tzinfo=timezone(timedelta(hours=4))),
        datetime(2026, 8, 16, 22, 30, tzinfo=timezone(timedelta(hours=-5))),
    ],
)
def test_date_label_renders_the_bytes_the_retired_date_key_did(captured_at):
    """archiver#523 moves no destination: the rename is a name, not a format.

    The retired ``date`` key rendered ``captured_at.astimezone(UTC).date().isoformat()``
    (``destination.py`` at ``d03b147b``). ``date_label`` must give the same
    bytes for the same occasion — across midnight and outside UTC too — or a
    rewritten frozen RepSpec would start writing to a new key. It is also the
    shared vocabulary's ``%Y-%m-%d``, spelled the way ``_DateProps`` spells it.
    """
    occasion = _occasion(captured_at=captured_at)
    retired = captured_at.astimezone(UTC).date().isoformat()

    rendered = render_destination(
        "archive/{source_revision.date_label}/{source_revision.id}.html",
        rep_fields={},
        occasion=occasion,
        org=None,
    )

    assert rendered == f"archive/{retired}/01JZZZZZZZZZZZZZZZZZZZZZZZ.html"
    assert occasion.values()["date_label"] == captured_at.astimezone(UTC).strftime("%Y-%m-%d")


def test_the_occasion_no_longer_supplies_date():
    """No alias (archiver#523): one name per spelling, so ``date`` is gone."""
    assert "date" not in _occasion().values()
    with pytest.raises(MalformedTemplateError, match="source_revision.date is not a value"):
        render_destination(
            "{source_revision.date}/{source_revision.id}",
            rep_fields={},
            occasion=_occasion(),
            org=None,
        )


def test_captured_at_renders_in_basic_iso_form():
    """Extended ISO carries colons; the basic form is the path-safe spelling."""
    rendered = render_destination(
        "{source_revision.captured_at}/{source_revision.id}",
        rep_fields={},
        occasion=_occasion(),
        org=None,
    )
    assert rendered.startswith("20260817T143005Z/")


def test_numeric_and_boolean_bag_values_render():
    rendered = render_destination(
        "{event.year}/{doc.final}/{source_revision.id}",
        rep_fields={"event": {"year": 2026}, "doc": {"final": True}},
        occasion=_occasion(),
        org=None,
    )
    assert rendered.startswith("2026/true/")


def test_same_occasion_renders_the_same_key_twice():
    """R2/T4: a redelivery must target the same key for the no-op path to be safe."""
    args = {
        "rep_fields": {"info_item": {"slug": "wa-lcb-notices"}},
        "occasion": _occasion(),
    }
    template = "archive/{info_item.slug}/{source_revision.fingerprint}.html"
    assert render_destination(template, **args, org=None) == render_destination(
        template, **args, org=None
    )


def test_occasion_value_wins_over_a_bag_namespace_of_the_same_name():
    """A bag cannot shadow the occasion — the reserved namespace is reserved."""
    rendered = render_destination(
        "{source_revision.date_label}/{source_revision.id}",
        rep_fields={"source_revision": {"date_label": "1999-01-01"}},
        occasion=_occasion(),
        org=None,
    )
    assert rendered.startswith("2026-08-17/")


# --- unrenderable ---


def test_missing_bag_value_is_unrenderable():
    """rep_fields is editable after assignment, so required_fields is not a guarantee."""
    with pytest.raises(MissingFieldError):
        render_destination(
            "{info_item.slug}/{source_revision.id}", rep_fields={}, occasion=_occasion(), org=None
        )


def test_a_slug_to_nothing_names_the_raw_field():
    """archiver#312: the issuance ``unrenderable`` detail carries this text."""
    with pytest.raises(MissingFieldError) as excinfo:
        render_destination(
            "{org.title_slug}/{source_revision.id}",
            rep_fields={"org": {"title": "!!!"}},
            occasion=_occasion(),
            org=None,
        )
    assert str(excinfo.value) == 'org.title "!!!" slugs to nothing (org.title_slug)'
    assert excinfo.value.field == "org.title_slug"


def test_null_bag_value_is_unrenderable():
    with pytest.raises(MissingFieldError):
        render_destination(
            "{info_item.slug}/{source_revision.id}",
            rep_fields={"info_item": {"slug": None}},
            occasion=_occasion(),
            org=None,
        )


def test_empty_bag_value_is_unrenderable():
    with pytest.raises(InvalidFieldValueError):
        render_destination(
            "{info_item.slug}/{source_revision.id}",
            rep_fields={"info_item": {"slug": ""}},
            occasion=_occasion(),
            org=None,
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
            org=None,
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
        render_destination(template, rep_fields={}, occasion=_occasion(), org=None)


def test_plain_relative_path_is_safe():
    assert render_destination(
        "archive/2026/{source_revision.id}.html", rep_fields={}, occasion=_occasion(), org=None
    ).endswith(".html")


# --- the occasion is checked too (CR #2, #3) ---


@pytest.mark.parametrize("value", ["a/b", "..", "a b", "x\\y", "a:b", ""])
def test_occasion_value_outside_the_segment_charset_refused(value):
    """Half the vocabulary skipping the charset check is half a guard."""
    with pytest.raises(InvalidOccasionError):
        render_destination(
            "x/{source_revision.id}",
            rep_fields={},
            occasion=_occasion(source_revision_id=value),
            org=None,
        )


def test_naive_captured_at_refused():
    """astimezone() on a naive value assumes VM-local and then stamps 'Z' on it —
    a wrong timestamp inside a permanent, citable path."""
    with pytest.raises(InvalidOccasionError):
        render_destination(
            "{source_revision.captured_at}/{source_revision.id}",
            rep_fields={},
            occasion=_occasion(captured_at=datetime(2026, 8, 17, 1, 30)),
            org=None,
        )


def test_non_utc_captured_at_is_converted_not_refused():
    """An aware value in another zone is unambiguous; only naive is refused."""
    rendered = render_destination(
        "{source_revision.date_label}/{source_revision.id}",
        rep_fields={},
        occasion=_occasion(
            captured_at=datetime(2026, 8, 17, 1, 30, tzinfo=timezone(timedelta(hours=4)))
        ),
        org=None,
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
        org=None,
    )


def test_probe_refuses_a_bag_value_that_cannot_be_a_segment():
    """Present and non-null satisfies required_fields; it does not make a path."""
    with pytest.raises(InvalidFieldValueError):
        probe_destination(
            {"path_template": "archive/{org.name}/{source_revision.id}.html"},
            rep_fields={"org": {"name": "WA LCB"}},
            org=None,
        )


def test_probe_refuses_a_missing_bag_value():
    with pytest.raises(MissingFieldError):
        probe_destination(
            {"path_template": "archive/{org.name}/{source_revision.id}.html"},
            rep_fields={},
            org=None,
        )


def test_probe_is_a_no_op_without_a_path_template():
    """Document validity is create-time's job; a partial document is not this
    check's failure to report."""
    assert probe_destination({"required_fields": []}, rep_fields={}, org=None) is None


def test_probe_returns_the_path_it_rendered():
    """``set_rep_fields`` compares a bag's path before and after a save (archiver#302)."""
    path = probe_destination(
        {"path_template": "archive/{info_item.slug}/{source_revision.year}.html"},
        rep_fields={"info_item": {"slug": "notices"}},
        occasion=_occasion(captured_at=datetime(2026, 10, 2, tzinfo=UTC)),
        org=None,
    )
    assert path == "archive/notices/2026.html"


def test_probe_renders_the_occasion_it_is_given():
    """Two bags compared against one occasion differ only where the bags do, and
    the occasion's revision is the one the paths show (archiver#333)."""
    document = {
        "path_template": "a/{org.title_slug}/{source_revision.datetime_time_segment}"
        "-{source_revision.id}.{source_revision.ext}"
    }
    occasion = _occasion(source_media_type="application/pdf")
    old, new = {"org": {"title": "Old Name"}}, {"org": {"title": "New Name"}}
    before = probe_destination(document, old, occasion=occasion, org=None)
    after = probe_destination(document, new, occasion=occasion, org=None)
    assert before == "a/old_name/2026_08_17-14_30_05-01JZZZZZZZZZZZZZZZZZZZZZZZ.pdf"
    assert after == "a/new_name/2026_08_17-14_30_05-01JZZZZZZZZZZZZZZZZZZZZZZZ.pdf"


def test_probe_without_an_occasion_renders_the_example_revision():
    path = probe_destination({"path_template": "a/{source_revision.id}"}, rep_fields={}, org=None)
    assert path == f"a/{EXAMPLE_REVISION_ID}"


def test_the_example_occasion_is_recognisably_not_a_revision():
    """Zeros for the id, now, HTML: a preview with no revision reads as an example
    and never as a citable id (archiver#308, moved to core for #333)."""
    occasion = example_occasion()

    assert occasion.source_revision_id == EXAMPLE_REVISION_ID == "0" * 26
    assert occasion.is_example
    assert occasion.values()["ext"] == "html"
    assert not _occasion().is_example


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
        org=None,
    )
    assert rendered == "2026/2026_08_17/2026_08_17-14_30_05/01JZZZZZZZZZZZZZZZZZZZZZZZ"


def test_segments_render_in_utc_whatever_zone_the_row_carries():
    rendered = render_destination(
        "{source_revision.datetime_time_segment}/{source_revision.id}",
        rep_fields={},
        occasion=_occasion(
            captured_at=datetime(2026, 8, 17, 16, 30, 5, tzinfo=timezone(timedelta(hours=2)))
        ),
        org=None,
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
        org=None,
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


def _assert_usable_segment(ext: str, context: object) -> None:
    assert destination._SEGMENT_SAFE.match(ext), (context, ext)
    assert ext not in destination._REFUSED_SEGMENTS, (context, ext)


def test_occasion_ext_is_co_cores_table_and_not_a_second_copy():
    """The occasion's ``ext`` is co-core's table and adds nothing (archiver#210, #529).

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
        ext = _occasion(source_media_type=media_type).values()["ext"]
        assert ext == extension_for_media_type(media_type), media_type


def test_the_extension_for_wrapper_is_gone():
    """``ext`` comes from ``SourceRevisionVars`` now (#529), so the wrapper had no caller.

    A wrapper with no caller is a second spelling of the agreement the test
    above guards, and the next reader would wonder which one the renderer uses.
    """
    assert not hasattr(destination, "extension_for")


def test_every_entry_in_co_cores_table_is_a_usable_path_segment():
    """The charset claim the occasion's ``ext`` relies on, pinned at its source (CR 8).

    ``_EXTENSION_SAFE`` used to enforce this locally and was deleted with the
    table, so the property is now a fact about another repository's data that
    this one depends on. Iterating the table itself rather than a list of media
    types is the difference between pinning it and sampling it: the sampled form
    covered 24 inputs and would have said nothing about a thirteenth entry added
    upstream — the same overclaim CR 2 was raised to remove, one layer up.

    Reads a private of co-core's deliberately. If it is ever renamed this fails
    at collection, loudly, which is the right outcome: the alternative is a
    guard that quietly stops guarding.
    """
    for media_type, ext in _MEDIA_TYPE_EXTENSIONS.items():
        _assert_usable_segment(ext, media_type)
    _assert_usable_segment(_FALLBACK_MEDIA_EXTENSION, "fallback")


def test_every_extension_co_core_yields_is_a_usable_path_segment():
    """The same property through the public surface, for the inputs we render.

    Kept beside the table-wide check so the guarantee survives the private above
    disappearing, and because these exercise what the table alone cannot:
    parameter-stripping, case-folding, ``None`` and the unregistered fallback.
    """
    for media_type in _MEDIA_TYPES_CHECKED:
        _assert_usable_segment(extension_for_media_type(media_type), media_type)


def test_no_local_extension_table_survives():
    """The delegation removed the table, the fallback and the ``mimetypes`` import.

    A structural assertion because the behavioural ones above cannot see a table
    that is still present but shadowed - and a resurrected local table would
    re-open the split silently, on whichever media types someone added to it.

    Scanned rather than grepped (CR 3): why parsing is the only honest way to
    ask this is in ``_import_scan``, with the scanner.
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
        org=None,
    )
    assert rendered == "wslcb-meeting_schedule/cafe_resume/01JZZZZZZZZZZZZZZZZZZZZZZZ"


def test_a_stored_slug_is_an_explicit_override():
    rendered = render_destination(
        "{org.title_slug}/{source_revision.id}",
        rep_fields={"org": {"title": "Anything At All", "title_slug": "custom"}},
        occasion=_occasion(),
        org=None,
    )
    assert rendered == "custom/01JZZZZZZZZZZZZZZZZZZZZZZZ"


def test_a_raw_placeholder_still_refuses_rather_than_rewrites():
    """Resolution adds ``_slug`` companions; it never slugifies a raw placeholder."""
    with pytest.raises(InvalidFieldValueError):
        render_destination(
            "{org.title}/{source_revision.id}",
            rep_fields={"org": {"title": "WA LCB"}},
            occasion=_occasion(),
            org=None,
        )


def test_probe_resolves_slugs_the_same_way():
    probe_destination(
        {"path_template": "{org.title_slug}/{source_revision.id}"},
        {"org": {"title": "Washington State LCB"}},
        org=None,
    )


# --- the golden rendering the epic was approved on (archiver#207) ---

# co-core's ``infoitem_revision`` location, read from its defaults rather than
# copied here (archiver#529). The expected key below stays a literal: it is what
# the epic approved, and the test pins that co-core's layout still renders it.
_INFOITEM_REVISION = StorageLocationKey.INFOITEM_REVISION
_GCS = StorageConfig.defaults().providers["gcs"]
_LOC = _GCS.locations[_INFOITEM_REVISION]
CANONICAL_LAYOUT = f"{_LOC.path_template}/{_LOC.filename_template}"


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
        org=None,
    )
    assert rendered == (
        "organizations/washington_state_liquor_and_cannabis_board/infoitems/"
        "public_hearings_and_outreach/2026/"
        "2026_09_09-18_54_02-public_hearings_and_outreach-01M23RDZKZS6FSPP1YZFBEQB2R.html"
    )


# --- co-core parity: one vocabulary, one layout (archiver#529, cannobserv#703) ---
#
# cannobserv#725 deletes its "Archiver-Rendered Locations" exception on the
# strength of these: Archiver's renderer and co-core's ``StorageProvider`` give
# one key for one revision.

_PARITY_OCCASIONS = [
    pytest.param(
        "01M23RDZKZS6FSPP1YZFBEQB2R",
        datetime(2026, 9, 9, 18, 54, 2, tzinfo=UTC),
        "text/html",
        id="utc-html",
    ),
    pytest.param(
        "01M26HZ3SAC8SY8S7Q2E9HJVXR",
        datetime(2026, 11, 27, 20, 0, 0, tzinfo=timezone(timedelta(hours=-8))),
        "application/pdf",
        id="west-of-utc-across-midnight-pdf",
    ),
    pytest.param(
        "01JZZZZZZZZZZZZZZZZZZZZZZZ",
        datetime(2026, 1, 1, 0, 30, 0, 999999, tzinfo=timezone(timedelta(hours=4))),
        "text/html; charset=utf-8",
        id="east-of-utc-across-new-year-params",
    ),
    pytest.param(
        "01JZZZZZZZZZZZZZZZZZZZZZZZ",
        datetime(2026, 8, 7, 3, 4, 5, tzinfo=UTC),
        None,
        id="no-media-type",
    ),
]


def _co_core_vars(revision_id, captured_at, media_type) -> SourceRevisionVars:
    return SourceRevisionVars(
        revision_id=revision_id,
        content_fingerprint=FINGERPRINT,
        media_type=media_type or "",
        dt=captured_at,
    )


@pytest.mark.parametrize(("revision_id", "captured_at", "media_type"), _PARITY_OCCASIONS)
def test_occasion_values_are_co_cores_rendered(revision_id, captured_at, media_type):
    """``values()`` is ``SourceRevisionVars.rendered()``: every key, every byte (#529)."""
    occasion = RenderOccasion(
        source_revision_id=revision_id,
        content_fingerprint=FINGERPRINT,
        captured_at=captured_at,
        source_media_type=media_type,
    )
    expected = _co_core_vars(revision_id, captured_at, media_type).rendered()
    assert occasion.values() == expected
    assert set(expected) == SourceRevisionVars.RENDER_KEYS


@pytest.mark.parametrize(("revision_id", "captured_at", "media_type"), _PARITY_OCCASIONS)
def test_infoitem_revision_renders_one_key_through_both_renderers(
    revision_id, captured_at, media_type
):
    """co-core's ``StorageProvider`` and ``render_destination`` agree on the layout (#529).

    The same revision, org title and item name go through ``ContextMap`` (via
    ``StorageProvider.location``) and through Archiver's own renderer, with
    the slugs derived on each side by its own code. One key comes out.
    """
    title = "Washington State Liquor and Cannabis Board"
    name = "Public Hearings & Outreach"
    context = StorageContext(
        org=OrgVars(title=title),
        info_item=InformationItemVars(name=name),
        source_revision=_co_core_vars(revision_id, captured_at, media_type),
        # The opt-in that makes a location render its filename_template.
        file=FileVars(),
    )
    co_core_key = (
        StorageProvider("gcs", _GCS, bucket="parity")
        .location(_INFOITEM_REVISION, context)
        .gcs_blob_name
    )

    archiver_key = render_destination(
        CANONICAL_LAYOUT,
        rep_fields={"org": {"title": title}, "info_item": {"name": name}},
        occasion=RenderOccasion(
            source_revision_id=revision_id,
            content_fingerprint=FINGERPRINT,
            captured_at=captured_at,
            source_media_type=media_type,
        ),
        org=None,
    )

    assert archiver_key == co_core_key


@pytest.mark.parametrize(
    ("title", "name"),
    [
        ("Liquor & Cannabis Board", "Public Hearings and Outreach"),
        ("WSLCB - Meeting Schedule", "Café Résumé"),
        ("  Board   of  Health ", "Rules: 2026/27 (draft)"),
    ],
)
def test_rep_fields_slugs_equal_co_cores_vars_slugs(title, name):
    """``org.title_slug`` and ``info_item.name_slug`` are the ``*Vars`` slugs (#206, #529).

    Both sides call ``normalize_string``. This pins that neither puts a step
    in front of it. Checked from a stored bag and from a linked org, the two
    ways ``org.title`` reaches the bag (#303).
    """
    from_bag = effective_rep_fields({"org": {"title": title}, "info_item": {"name": name}}, None)
    from_org = effective_rep_fields(
        {"info_item": {"name": name}}, OrgValues(name=title, acronym=None)
    )

    for bag in (from_bag, from_org):
        assert bag["org"]["title_slug"] == OrgVars(title=title).title_slug
        assert bag["info_item"]["name_slug"] == InformationItemVars(name=name).name_slug


def test_the_keys_co_core_added_render():
    """``month``, ``day`` and ``day_unpadded`` arrive with the adoption (#529), in UTC."""
    rendered = render_destination(
        "{source_revision.month}/{source_revision.day}/{source_revision.day_unpadded}/"
        "{source_revision.id}",
        rep_fields={},
        occasion=_occasion(
            captured_at=datetime(2026, 8, 7, 1, 0, tzinfo=timezone(timedelta(hours=2)))
        ),
        org=None,
    )
    assert rendered == "08/06/6/01JZZZZZZZZZZZZZZZZZZZZZZZ"


def test_date_label_below_year_1000_is_co_cores():
    """The one byte split between the renderers, and co-core wins it (#523's relay, #529).

    Archiver rendered ``date_label`` with ``isoformat()`` (``0999-01-02``).
    co-core uses ``%Y-%m-%d``, which glibc leaves unpadded (``999-01-02``).
    One renderer is the point of #529, so Archiver takes co-core's value
    instead of keeping a second implementation for a year no capture can
    carry. Production's only template doesn't name ``date_label``, and every
    capture is from 2026, so no destination moves.

    The pin is "whatever co-core renders", not a literal: ``%Y`` below 1000 is
    a property of the libc. ``year`` and the segments already used ``strftime``
    and were never split.
    """
    captured_at = datetime(999, 1, 2, 3, 4, 5, tzinfo=UTC)
    values = _occasion(captured_at=captured_at).values()
    co_core = SourceRevisionVars(dt=captured_at)
    assert values["date_label"] == co_core.date_label
    assert values["year"] == co_core.year


@pytest.mark.parametrize(
    ("override", "key"),
    [
        ({"source_revision_id": ""}, "source_revision.id"),
        ({"content_fingerprint": ""}, "source_revision.fingerprint"),
        ({"content_fingerprint": "sha256:"}, "source_revision.fingerprint"),
    ],
)
def test_an_absent_occasion_value_is_an_occasion_error(override, key):
    """co-core leaves out an absent value; Archiver refuses it as the caller's bug (#529).

    ``rendered()`` drops ``id`` for an empty ULID and ``fingerprint`` for an
    empty digest, so a renderer that only looked keys up would report a
    missing *template* key. The fault is the occasion's, as it was when the
    segment check refused ``""``, and the template need not name the key.
    """
    with pytest.raises(InvalidOccasionError) as exc:
        render_destination(
            "x/{source_revision.date_label}",
            rep_fields={},
            occasion=_occasion(**override),
            org=None,
        )
    assert exc.value.key == key


def test_the_example_occasion_supplies_every_key():
    """Previews render whatever key a RepSpec names (#308, #333), the new three included."""
    assert set(example_occasion().values()) == SourceRevisionVars.RENDER_KEYS
