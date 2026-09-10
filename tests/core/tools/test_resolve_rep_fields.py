"""Tests for resolve_rep_fields slug normalization tool."""

from co_core.pure.util.text import normalize_string

from src.core.tools.resolve_rep_fields import resolve_rep_fields, slugify

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
