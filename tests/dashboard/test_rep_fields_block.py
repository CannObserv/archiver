"""The Fields block's view model: rows, badges, readouts, the form parse (archiver#307)."""

import pytest

from src.core.rep_fields import OrgValues
from src.dashboard.rep_fields_block import (
    FieldsFormError,
    build_fields,
    parse_fields_form,
    suggest_item_name,
)

_ORG_SPEC = ("Org Layout", {"required_fields": ["org.title_slug"]})


def _row(view, key):
    return next(r for r in view.rows if r.key == key)


# ---------------------------------------------------------------------------
# Rows: one per raw key the required keys come from
# ---------------------------------------------------------------------------


def test_a_required_slug_key_is_entered_as_its_raw_field():
    view = build_fields({}, [_ORG_SPEC], org=None, item_name="x")

    assert [r.key for r in view.rows] == ["org.title"]
    assert _row(view, "org.title").required_by == ("Org Layout",)


def test_a_raw_key_required_beside_its_slug_is_one_row():
    spec = ("Both", {"required_fields": ["org.title", "org.title_slug"]})

    view = build_fields({}, [spec], org=None, item_name="x")

    assert [r.key for r in view.rows] == ["org.title"]


def test_rows_span_every_spec_and_name_each_spec_once():
    other = ("Name Layout", {"required_fields": ["info_item.name", "org.title_slug"]})

    view = build_fields({}, [_ORG_SPEC, other], org=None, item_name="x")

    assert [r.key for r in view.rows] == ["org.title", "info_item.name"]
    assert _row(view, "org.title").required_by == ("Org Layout", "Name Layout")


def test_the_acronym_or_title_composite_asks_for_both_raw_fields():
    spec = ("Short", {"required_fields": ["org.acronym_or_title_slug"]})

    view = build_fields({}, [spec], org=None, item_name="x")

    assert [r.key for r in view.rows] == ["org.acronym", "org.title"]


def test_a_malformed_required_entry_makes_no_row():
    spec = ("Bad", {"required_fields": ["nodot"]})

    assert build_fields({}, [spec], org=None, item_name="x").rows == ()


# ---------------------------------------------------------------------------
# Badges and the slug readout, from the effective bag
# ---------------------------------------------------------------------------


def test_a_stored_value_reads_stored_with_its_derived_slug():
    view = build_fields(
        {"org": {"title": "WSLCB - Meeting Schedule"}}, [_ORG_SPEC], org=None, item_name="x"
    )

    row = _row(view, "org.title")
    assert row.badge == "stored"
    assert row.value == "WSLCB - Meeting Schedule"
    assert [(r.key, r.value) for r in row.readouts] == [
        ("org.title_slug", "wslcb-meeting_schedule")
    ]


def test_an_absent_value_reads_missing():
    row = _row(build_fields({}, [_ORG_SPEC], org=None, item_name="x"), "org.title")

    assert row.badge == "missing"
    assert row.readouts[0].value is None


def test_a_stored_null_reads_missing():
    spec = ("Raw", {"required_fields": ["info_item.name"]})

    row = _row(
        build_fields({"info_item": {"name": None}}, [spec], org=None, item_name="x"),
        "info_item.name",
    )

    assert row.badge == "missing"


def test_a_value_that_slugs_to_nothing_is_its_own_state_worded_by_the_gate():
    """archiver#312: not *missing* - the operator typed a value, and the remedy differs."""
    row = _row(
        build_fields({"org": {"title": "!!!"}}, [_ORG_SPEC], org=None, item_name="x"), "org.title"
    )

    assert row.badge == "slugs_to_nothing"
    assert row.reason == 'org.title "!!!" slugs to nothing (org.title_slug)'


def test_an_empty_slug_is_reported_even_while_another_key_is_missing():
    """The gate reports missing keys first; a per-row badge does not wait on them."""
    spec = ("Two", {"required_fields": ["org.title_slug", "info_item.name"]})

    view = build_fields({"org": {"title": "!!!"}}, [spec], org=None, item_name="x")

    assert _row(view, "org.title").badge == "slugs_to_nothing"
    assert _row(view, "info_item.name").badge == "missing"


def test_the_composite_blames_the_field_it_took():
    spec = ("Short", {"required_fields": ["org.acronym_or_title_slug"]})

    view = build_fields(
        {"org": {"acronym": "!!!", "title": "Board"}}, [spec], org=None, item_name="x"
    )

    assert _row(view, "org.acronym").badge == "slugs_to_nothing"
    assert _row(view, "org.title").badge == "stored"


def test_a_stored_slug_is_an_override():
    bag = {"org": {"title": "Board", "title_slug": "custom"}}

    row = _row(build_fields(bag, [_ORG_SPEC], org=None, item_name="x"), "org.title")

    assert row.badge == "override"
    assert row.overrides == (("org.title_slug", "custom"),)
    assert row.readouts[0].value == "custom"


def test_an_override_satisfies_a_row_whose_raw_field_is_absent():
    row = _row(
        build_fields({"org": {"title_slug": "custom"}}, [_ORG_SPEC], org=None, item_name="x"),
        "org.title",
    )

    assert row.badge == "override"
    assert row.value is None


def test_a_composite_override_gets_one_input_but_marks_both_rows():
    """Both raw rows feed acronym_or_title_slug; two inputs for one key would make
    the form post it twice, which the strict parse refuses on every save (CR 1)."""
    spec = ("Short", {"required_fields": ["org.acronym_or_title_slug"]})
    bag = {"org": {"acronym": "A", "title": "T", "acronym_or_title_slug": "x"}}

    view = build_fields(bag, [spec], org=None, item_name="x")

    assert [o.key for r in view.rows for o in r.overrides] == ["org.acronym_or_title_slug"]
    assert [r.badge for r in view.rows] == ["override", "override"]


def test_a_linked_org_supplies_its_fields_read_only():
    """Ready for archiver#304: the org comes in through effective_rep_fields."""
    row = _row(
        build_fields({}, [_ORG_SPEC], org=OrgValues(name="Board", acronym=None), item_name="x"),
        "org.title",
    )

    assert row.badge == "from_power_map"
    assert row.value == "Board"
    assert row.readouts[0].value == "board"


# ---------------------------------------------------------------------------
# Other fields
# ---------------------------------------------------------------------------


def test_stored_keys_no_spec_requires_are_other_fields():
    bag = {"org": {"title": "Board", "note": "n"}, "meta": {"year": 2024}}

    view = build_fields(bag, [_ORG_SPEC], org=None, item_name="x")

    assert [(f.key, f.value) for f in view.other_fields] == [
        ("org.note", "n"),
        ("meta.year", 2024),
    ]


def test_an_override_is_not_also_an_other_field():
    bag = {"org": {"title": "Board", "title_slug": "custom"}}

    assert build_fields(bag, [_ORG_SPEC], org=None, item_name="x").other_fields == ()


def test_a_legacy_flat_key_is_shown_so_the_save_can_name_it():
    """Pre-#302 bags can hold top-level scalars; the v1 gate refuses them on save."""
    view = build_fields({"key1": "value1"}, [], org=None, item_name="x")

    assert [(f.key, f.value) for f in view.other_fields] == [("key1", "value1")]


def test_a_non_string_value_round_trips_as_json():
    field = build_fields({"meta": {"year": 2024}}, [], org=None, item_name="x").other_fields[0]

    assert (field.input_type, field.input_value) == ("json", "2024")


def test_a_string_value_round_trips_as_text():
    field = build_fields({"meta": {"label": "2024"}}, [], org=None, item_name="x").other_fields[0]

    assert (field.input_type, field.input_value) == ("string", "2024")


# ---------------------------------------------------------------------------
# info_item.name suggestion
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "acronym", "expected"),
    [
        ("WSLCB - Meeting Schedule", "WSLCB", "Meeting Schedule"),
        ("WSLCB - Meeting Schedule", None, "Meeting Schedule"),
        ("Meeting Schedule", "WSLCB", None),
        ("Board - Meeting Schedule", "WSLCB", None),
        ("WSLCB - ", "WSLCB", None),
    ],
)
def test_suggest_item_name_drops_a_leading_acronym(name, acronym, expected):
    assert suggest_item_name(name, acronym) == expected


def test_the_name_row_offers_the_suggestion():
    spec = ("Name Layout", {"required_fields": ["info_item.name"]})

    view = build_fields({}, [spec], org=None, item_name="WSLCB - Meeting Schedule")

    assert _row(view, "info_item.name").suggestion == "Meeting Schedule"


def test_the_suggestion_uses_the_bags_acronym():
    spec = ("Name Layout", {"required_fields": ["info_item.name"]})
    bag = {"org": {"acronym": "WA LCB"}}

    view = build_fields(bag, [spec], org=None, item_name="WA LCB - Meeting Schedule")

    assert _row(view, "info_item.name").suggestion == "Meeting Schedule"


def test_no_suggestion_once_the_value_matches_it():
    spec = ("Name Layout", {"required_fields": ["info_item.name"]})
    bag = {"info_item": {"name": "Meeting Schedule"}}

    view = build_fields(bag, [spec], org=None, item_name="WSLCB - Meeting Schedule")

    assert _row(view, "info_item.name").suggestion is None


def test_only_the_name_row_offers_a_suggestion():
    view = build_fields({}, [_ORG_SPEC], org=None, item_name="WSLCB - Meeting Schedule")

    assert _row(view, "org.title").suggestion is None


# ---------------------------------------------------------------------------
# The form parse
# ---------------------------------------------------------------------------


def test_parse_builds_a_namespaced_bag():
    bag = parse_fields_form(["org.title", "meta.year"], ["Board", "2024"], ["string", "json"])

    assert bag == {"org": {"title": "Board"}, "meta": {"year": 2024}}


def test_parse_keeps_text_typed_over_a_json_value():
    """The type marker is invisible: retyping 2024 as text is an edit, not an error (CR 2)."""
    bag = parse_fields_form(["meta.year", "meta.draft"], ["circa 2024", "true"], ["json", "json"])

    assert bag == {"meta": {"year": "circa 2024", "draft": True}}


def test_parse_drops_blank_values():
    assert parse_fields_form(["org.title", "org.acronym"], ["Board", "  "], ["string"] * 2) == {
        "org": {"title": "Board"}
    }


def test_parse_skips_a_wholly_blank_added_row():
    assert parse_fields_form(["", "org.title"], ["", "Board"], ["string"] * 2) == {
        "org": {"title": "Board"}
    }


def test_parse_passes_a_flat_key_through_for_the_gate_to_refuse():
    assert parse_fields_form(["key1"], ["value1"], ["string"]) == {"key1": "value1"}


def test_parse_trims_the_key_but_not_the_value():
    assert parse_fields_form([" org.title "], [" Board "], ["string"]) == {
        "org": {"title": " Board "}
    }


@pytest.mark.parametrize(
    ("keys", "values", "types", "fragment"),
    [
        (["", "x"], ["v", "y"], ["string"] * 2, "no name"),
        (["org.title", "org.title"], ["a", "b"], ["string"] * 2, "org.title"),
        (["org", "org.title"], ["a", "b"], ["string"] * 2, "org"),
        (["org.title"], ["a", "b"], ["string"], "mismatched"),
    ],
)
def test_parse_refuses_what_it_cannot_build(keys, values, types, fragment):
    with pytest.raises(FieldsFormError, match=fragment):
        parse_fields_form(keys, values, types)


def test_a_lenient_parse_reads_what_it_can():
    """The live readout reads half-typed input; only the save refuses it."""
    bag = parse_fields_form(
        ["org.title", "org.title", "", "org"],
        ["A", "B", "orphan", "flat"],
        ["string", "string", "string", "string"],
        strict=False,
    )

    assert bag == {"org": {"title": "B"}}


def test_a_lenient_parse_survives_mismatched_lists():
    assert parse_fields_form(["org.title"], ["A", "B"], [], strict=False) == {"org": {"title": "A"}}
