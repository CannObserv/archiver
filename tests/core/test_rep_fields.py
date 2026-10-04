"""Tests for rep_fields slug normalization (``src.core.rep_fields``)."""

import copy

import pytest
from co_core.pure.util.text import normalize_string

from src.core.rep_fields import (
    OrgValues,
    effective_rep_fields,
    empty_slug_reason,
    resolve_rep_fields,
    slugify,
)

# ---------------------------------------------------------------------------
# slugify corner cases
# ---------------------------------------------------------------------------


class TestSlugify:
    def test_sentence_with_spaces(self):
        assert slugify("Washington State LCB") == "washington_state_lcb"

    def test_all_caps(self):
        assert slugify("WSLCB") == "wslcb"

    def test_punctuation(self):
        assert slugify("Hello, World!") == "hello_world"

    def test_leading_trailing_spaces(self):
        assert slugify("  spaces  ") == "spaces"

    def test_already_slug(self):
        assert slugify("ALREADY_SLUG") == "already_slug"

    # archiver#206: one slugger cluster-wide. The storage framework's *Vars
    # derive every _slug with co-core's normalize_string; a path segment built
    # here has to match the sibling directories built there.

    def test_dash_separated_title_keeps_the_dash(self):
        assert slugify("WSLCB - Meeting Schedule") == "wslcb-meeting_schedule"

    def test_diacritics_fold(self):
        assert slugify("Café Résumé") == "cafe_resume"

    def test_is_the_shared_normalizer(self):
        for raw in ("WA Governor - Bill Actions", "Hello, World!", "Café", "x/y"):
            assert slugify(raw) == normalize_string(raw)


# ---------------------------------------------------------------------------
# resolve_rep_fields
# ---------------------------------------------------------------------------

DESIGN_DOC_BAG = {
    "org": {
        "acronym": "WSLCB",
        "title": "Washington State Liquor and Cannabis Board",
    },
    "event": {
        "year": "2025",
        "date_label": "2025-04-15",
        "type_slug": "board_meeting",
    },
    "file": {
        "label": "Agenda",
        "ext": "pdf",
    },
}


class TestResolveRepFields:
    def test_round_trip_design_doc_example(self):
        result = resolve_rep_fields(DESIGN_DOC_BAG)

        # org: slug companions for each string field
        assert result["org"]["acronym_slug"] == "wslcb"
        assert result["org"]["title_slug"] == "washington_state_liquor_and_cannabis_board"

        # org: acronym_or_title prefers acronym
        assert result["org"]["acronym_or_title"] == "WSLCB"
        assert result["org"]["acronym_or_title_slug"] == "wslcb"

        # event: slugs added
        assert result["event"]["year_slug"] == "2025"
        assert result["event"]["date_label_slug"] == "2025_04_15"

        # event: existing type_slug is preserved (not overwritten)
        assert result["event"]["type_slug"] == "board_meeting"
        # no type_slug_slug should be added (key ends with _slug)
        assert "type_slug_slug" not in result["event"]

        # file: slugs added
        assert result["file"]["label_slug"] == "agenda"
        assert result["file"]["ext_slug"] == "pdf"

    def test_idempotent(self):
        first = resolve_rep_fields(DESIGN_DOC_BAG)
        second = resolve_rep_fields(first)
        assert first == second

    def test_unknown_namespace_passes_through(self):
        bag = {"weird": {"x": "y"}}
        result = resolve_rep_fields(bag)
        assert result["weird"]["x"] == "y"
        assert result["weird"]["x_slug"] == "y"

    def test_non_string_field_unchanged(self):
        bag = {"event": {"year": 2025}}
        result = resolve_rep_fields(bag)
        assert result["event"]["year"] == 2025
        assert "year_slug" not in result["event"]

    def test_empty_bag(self):
        assert resolve_rep_fields({}) == {}

    def test_acronym_or_title_prefers_acronym(self):
        bag = {"org": {"acronym": "WSLCB", "title": "Long Title"}}
        result = resolve_rep_fields(bag)
        assert result["org"]["acronym_or_title"] == "WSLCB"
        assert result["org"]["acronym_or_title_slug"] == "wslcb"

    def test_acronym_or_title_requires_both_keys(self):
        """Only title present — no acronym_or_title derived (need both keys per spec)."""
        bag = {"org": {"title": "Long Title"}}
        result = resolve_rep_fields(bag)
        assert "acronym_or_title" not in result["org"]
        assert "acronym_or_title_slug" not in result["org"]

    def test_non_dict_namespace_passes_through(self):
        """Non-dict namespace values are passed through unchanged."""
        bag = {"meta": "some_string_value"}
        result = resolve_rep_fields(bag)
        assert result["meta"] == "some_string_value"


# ---------------------------------------------------------------------------
# CR 1: a raw value that normalizes to nothing derives no companion
#
# The storage framework's rule (cannobserv docs/STORAGE_VARS.md S2): a slug
# property returns None on empty raw input, never "". Writing "" here made the
# key *present*, so validate_rep_fields_against_spec reported a bag valid that
# can never render.
# ---------------------------------------------------------------------------


class TestEmptySlugsAreAbsent:
    def test_a_value_that_slugs_to_nothing_derives_no_companion(self):
        result = resolve_rep_fields({"org": {"title": "!!!"}})
        assert result["org"]["title"] == "!!!"
        assert "title_slug" not in result["org"]

    def test_acronym_or_title_slug_is_absent_when_it_would_be_empty(self):
        result = resolve_rep_fields({"org": {"acronym": "!!!", "title": "???"}})
        assert result["org"]["acronym_or_title"] == "!!!"
        assert "acronym_or_title_slug" not in result["org"]

    def test_an_empty_raw_string_still_derives_nothing(self):
        result = resolve_rep_fields({"org": {"title": ""}})
        assert "title_slug" not in result["org"]

    def test_a_usable_value_still_derives(self):
        result = resolve_rep_fields({"org": {"title": "WA LCB"}})
        assert result["org"]["title_slug"] == "wa_lcb"


# ---------------------------------------------------------------------------
# effective_rep_fields - the single resolution point (archiver#303)
#
# Precedence, lowest first: the linked org's name/acronym, then the stored
# bag, then resolve_rep_fields' derivations (which never replace a stored
# key). The refusal of a stored org.title/org.acronym while linked is #304's.
# ---------------------------------------------------------------------------

WA_LCB = OrgValues(name="Washington State Liquor and Cannabis Board", acronym="WSLCB")


class TestEffectiveRepFields:
    @pytest.mark.parametrize(
        "bag",
        [
            {},
            DESIGN_DOC_BAG,
            {"org": {"title": "WA LCB", "title_slug": "override"}},
            {"meta": "some_string_value", "event": {"year": 2025}},
            {"org": {"title": "!!!"}},
        ],
    )
    def test_no_org_is_resolve_rep_fields_exactly(self, bag):
        assert effective_rep_fields(bag, None) == resolve_rep_fields(bag)

    def test_an_org_supplies_title_and_acronym(self):
        result = effective_rep_fields({}, WA_LCB)
        assert result["org"]["title"] == "Washington State Liquor and Cannabis Board"
        assert result["org"]["acronym"] == "WSLCB"
        assert result["org"]["title_slug"] == "washington_state_liquor_and_cannabis_board"
        assert result["org"]["acronym_or_title_slug"] == "wslcb"

    def test_an_org_merges_beside_other_stored_org_keys(self):
        result = effective_rep_fields({"org": {"jurisdiction": "WA"}}, WA_LCB)
        assert result["org"]["jurisdiction"] == "WA"
        assert result["org"]["title"] == WA_LCB.name

    def test_other_namespaces_are_untouched(self):
        bag = {"info_item": {"name": "Agenda"}}
        result = effective_rep_fields(bag, WA_LCB)
        assert result["info_item"] == resolve_rep_fields(bag)["info_item"]

    def test_a_none_acronym_is_skipped(self):
        result = effective_rep_fields({}, OrgValues(name="WA LCB", acronym=None))
        assert result["org"] == {"title": "WA LCB", "title_slug": "wa_lcb"}

    def test_a_stored_title_wins(self):
        result = effective_rep_fields({"org": {"title": "Hand Typed"}}, WA_LCB)
        assert result["org"]["title"] == "Hand Typed"
        assert result["org"]["title_slug"] == "hand_typed"
        assert result["org"]["acronym"] == "WSLCB"

    def test_a_stored_acronym_wins(self):
        result = effective_rep_fields({"org": {"acronym": "LCB"}}, WA_LCB)
        assert result["org"]["acronym"] == "LCB"
        assert result["org"]["acronym_or_title"] == "LCB"

    def test_a_stored_slug_stays_an_override(self):
        result = effective_rep_fields({"org": {"title_slug": "wslcb"}}, WA_LCB)
        assert result["org"]["title_slug"] == "wslcb"
        assert result["org"]["title"] == WA_LCB.name

    def test_the_stored_bag_is_not_mutated(self):
        bag = {"org": {"jurisdiction": "WA"}}
        before = copy.deepcopy(bag)
        effective_rep_fields(bag, WA_LCB)
        assert bag == before

    def test_a_stored_non_dict_org_replaces_the_org_values(self):
        """Stored wins at the namespace too; shape validation is what refuses this bag."""
        assert effective_rep_fields({"org": "WA LCB"}, WA_LCB) == {"org": "WA LCB"}


class TestEmptySlugReason:
    """archiver#312: name the raw field the operator typed, not the derived key."""

    def test_names_the_raw_field_and_its_value(self):
        resolved = effective_rep_fields({"org": {"title": "!!!"}}, None)
        assert empty_slug_reason(resolved, "org", "title_slug") == (
            'org.title "!!!" slugs to nothing (org.title_slug)'
        )

    def test_names_the_source_of_acronym_or_title(self):
        resolved = effective_rep_fields({"org": {"acronym": "", "title": "!!!"}}, None)
        assert empty_slug_reason(resolved, "org", "acronym_or_title_slug") == (
            'org.title "!!!" slugs to nothing (org.acronym_or_title_slug)'
        )

    def test_names_the_acronym_when_it_was_preferred(self):
        resolved = effective_rep_fields({"org": {"acronym": "--", "title": "WA LCB"}}, None)
        assert empty_slug_reason(resolved, "org", "acronym_or_title_slug") == (
            'org.acronym "--" slugs to nothing (org.acronym_or_title_slug)'
        )

    def test_names_the_linked_org_name_as_org_title(self):
        resolved = effective_rep_fields({}, OrgValues(name="???", acronym=None))
        assert empty_slug_reason(resolved, "org", "title_slug") == (
            'org.title "???" slugs to nothing (org.title_slug)'
        )

    @pytest.mark.parametrize(
        ("bag", "key"),
        [
            ({}, "title_slug"),  # no raw value at all: a plain miss
            ({"org": {"title": "WA LCB"}}, "title_slug"),  # slugged fine
            ({"org": {"title": "!!!", "title_slug": None}}, "title_slug"),  # stored null
            ({"org": {"year": 2025}}, "year_slug"),  # non-strings get no companion
            ({"org": {"title": "!!!"}}, "title"),  # not a _slug key
            ({"org": "flat"}, "title_slug"),  # namespace is not a dict
        ],
    )
    def test_is_none_unless_a_raw_string_slugged_to_nothing(self, bag, key):
        assert empty_slug_reason(effective_rep_fields(bag, None), "org", key) is None
