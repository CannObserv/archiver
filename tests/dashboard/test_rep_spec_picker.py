"""The Add-a-spec picker's view model: readiness, and the path each spec renders (archiver#308)."""

from datetime import UTC, datetime

from ulid import ULID

from src.core.models import RepSpec
from src.core.replication.destination import RenderOccasion
from src.dashboard.providers import UNWRITABLE_PROVIDERS
from src.dashboard.rep_spec_picker import EXAMPLE_REVISION_ID, build_picker, example_occasion

_ORG_PATH = "organizations/{org.title_slug}/{source_revision.id}.{source_revision.ext}"
_REVISION_ID = "01JZ0000000000000000000000"
_OCCASION = RenderOccasion(
    source_revision_id=_REVISION_ID,
    content_fingerprint="sha256:" + "a" * 64,
    captured_at=datetime(2026, 5, 2, tzinfo=UTC),
    source_media_type="text/html",
)


def _spec(
    *required: str, path_template: str | None = _ORG_PATH, provider: str = "gcs", name: str = "S"
) -> RepSpec:
    document: dict = {"provider": provider, "required_fields": list(required)}
    if path_template is not None:
        document["path_template"] = path_template
    return RepSpec(
        rep_spec_id=ULID(), provider=provider, name=name, schema_version=1, document=document
    )


def _only(bag: dict, spec: RepSpec, occasion: RenderOccasion = _OCCASION):
    (entry,) = build_picker(bag, [spec], occasion=occasion, org=None)
    return entry


def test_a_ready_spec_renders_its_path_against_the_occasion():
    entry = _only({"org": {"title": "WSLCB Board"}}, _spec("org.title_slug"))

    assert entry.readiness == "ready"
    assert entry.ready
    assert entry.path == f"organizations/wslcb_board/{_REVISION_ID}.html"
    assert entry.needs == ()
    assert entry.reason is None


def test_a_spec_missing_a_slug_key_needs_the_raw_key_the_operator_types():
    entry = _only({}, _spec("org.title_slug"))

    assert entry.readiness == "needs"
    assert not entry.ready
    assert entry.needs == ("org.title",)
    assert entry.path is None
    assert entry.template == _ORG_PATH


def test_a_missing_composite_needs_either_raw_key():
    spec = _spec("org.acronym_or_title_slug", path_template="o/{org.acronym_or_title_slug}")

    entry = _only({}, spec)

    assert entry.needs == ("org.acronym or org.title",)


def test_a_plain_required_key_is_needed_as_itself():
    entry = _only(
        {"org": {"title": "WSLCB"}},
        _spec(
            "org.title_slug", "info_item.name", path_template="o/{org.title_slug}/{info_item.name}"
        ),
    )

    assert entry.needs == ("info_item.name",)


def test_a_value_that_slugs_to_nothing_cannot_render_in_the_gates_words():
    """archiver#312: the gate names the raw field; the picker shows it verbatim."""
    entry = _only({"org": {"title": "!!!"}}, _spec("org.title_slug"))

    assert entry.readiness == "unrenderable"
    assert entry.reason == 'org.title "!!!" slugs to nothing (org.title_slug)'
    assert entry.path is None


def test_a_value_that_is_not_a_segment_cannot_render():
    entry = _only(
        {"org": {"name": "WA LCB"}},
        _spec("org.name", path_template="a/{org.name}/{source_revision.id}"),
    )

    assert entry.readiness == "unrenderable"
    assert "org.name" in entry.reason


def test_an_unwritable_provider_is_disabled_with_its_reason():
    entry = _only({}, _spec(provider="ia"))

    assert entry.readiness == "unwritable"
    assert entry.reason == UNWRITABLE_PROVIDERS["ia"]
    assert not entry.ready


def test_a_spec_with_no_path_template_is_ready_with_no_path():
    entry = _only({}, _spec(path_template=None))

    assert entry.ready
    assert entry.path is None


def test_entries_keep_the_order_they_are_given():
    specs = [_spec(name="B"), _spec(name="A")]

    entries = build_picker({}, specs, occasion=_OCCASION, org=None)

    assert [e.name for e in entries] == ["B", "A"]
    assert [e.rep_spec_id for e in entries] == [str(s.rep_spec_id) for s in specs]


def test_the_example_occasion_renders_a_recognisable_revision():
    occasion = example_occasion()

    entry = _only({"org": {"title": "WSLCB"}}, _spec("org.title_slug"), occasion)

    assert entry.path == f"organizations/wslcb/{EXAMPLE_REVISION_ID}.html"
