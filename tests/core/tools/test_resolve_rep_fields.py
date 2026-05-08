"""Tests for resolve_rep_fields slug normalization tool."""

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
