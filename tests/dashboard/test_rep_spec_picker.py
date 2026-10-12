"""The Add-a-spec picker's view model: readiness, and the path each spec renders (archiver#308)."""

from datetime import UTC, datetime

import pytest
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
    *required: str, path_template: str = _ORG_PATH, provider: str = "gcs", name: str = "S", **extra
) -> RepSpec:
    """A document ``validate_rep_spec`` accepts unless ``extra`` breaks it (archiver#334)."""
    document: dict = {
        "provider": provider,
        "credentials_alias": f"{provider}-publication",
        "path_template": path_template,
        "required_fields": list(required),
        **extra,
    }
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
    spec = _spec(
        "org.acronym_or_title_slug",
        path_template="o/{org.acronym_or_title_slug}/{source_revision.id}",
    )

    entry = _only({}, spec)

    assert entry.needs == ("org.acronym or org.title",)


def test_a_plain_required_key_is_needed_as_itself():
    entry = _only(
        {"org": {"title": "WSLCB"}},
        _spec(
            "org.title_slug",
            "info_item.name",
            path_template="o/{org.title_slug}/{info_item.name}/{source_revision.id}",
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


@pytest.mark.parametrize(
    ("extra", "reason"),
    [
        ({"bucket": "b"}, "Additional properties are not allowed ('bucket' was unexpected)"),
        (
            {"object_options": {"storage_class": "HOT"}},
            "object_options/storage_class: 'HOT' is not one of",
        ),
        ({"path_template": "archive/latest.html"}, "path_template: path_template needs a"),
    ],
    ids=["envelope", "provider-sub-schema", "template-contract"],
)
def test_a_document_failing_validation_is_invalid_with_its_first_error(extra, reason):
    """archiver#334: the assign would refuse it, so the picker never calls it Ready."""
    entry = _only({"org": {"title": "WSLCB"}}, _spec("org.title_slug", **extra))

    assert entry.readiness == "invalid"
    assert not entry.ready
    assert entry.reason.startswith(reason)
    assert entry.needs == ()
    assert entry.path is None


def test_an_invalid_document_counts_the_errors_it_does_not_show():
    spec = _spec("org.title_slug", bucket="b", object_options={"storage_class": "HOT"})

    entry = _only({}, spec)

    assert entry.reason.endswith("(and 1 more)")


def test_a_document_with_no_path_template_is_invalid():
    """The envelope requires one: what was *Ready, no path* is now refused."""
    spec = _spec()
    del spec.document["path_template"]

    entry = _only({}, spec)

    assert entry.readiness == "invalid"
    assert entry.template is None
    assert "'path_template' is a required property" in entry.reason


def test_an_invalid_document_is_judged_before_the_bag():
    """No bag can fix the spec, so *Needs* would send the operator the wrong way."""
    entry = _only({}, _spec("org.title_slug", bucket="b"))

    assert entry.readiness == "invalid"


def test_entries_keep_the_order_they_are_given():
    specs = [_spec(name="B"), _spec(name="A")]

    entries = build_picker({}, specs, occasion=_OCCASION, org=None)

    assert [e.name for e in entries] == ["B", "A"]
    assert [e.rep_spec_id for e in entries] == [str(s.rep_spec_id) for s in specs]


def test_the_example_occasion_renders_a_recognisable_revision():
    occasion = example_occasion()

    entry = _only({"org": {"title": "WSLCB"}}, _spec("org.title_slug"), occasion)

    assert entry.path == f"organizations/wslcb/{EXAMPLE_REVISION_ID}.html"


def test_a_bag_off_the_v1_shape_cannot_render_rather_than_needing_its_bad_key():
    """CR 3. The gate files shape errors under ``missing``; read as *Needs*, a
    pre-#302 flat key would be a key to add, when it is one to fix."""
    entry = _only({"flat": "x", "org": {"title": "WSLCB"}}, _spec("org.title_slug"))

    assert entry.readiness == "unrenderable"
    assert entry.needs == ()
    assert entry.reason.startswith("Rep Fields are off the v1 shape: flat: ")
