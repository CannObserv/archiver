"""SourceSpec validator wrapper tests."""

from src.core.source_spec_schema.validator import (
    validate_fragment_source_spec,
    validate_root_source_spec,
    validate_source_spec,
)


def _root_doc(url: str = "https://example.com/p") -> dict:
    return {
        "schema_version": 1,
        "target": {"url": url},
        "extraction": {"algorithm": "full_page"},
        "fingerprint": {},
    }


def _fragment_doc() -> dict:
    return {
        "schema_version": 1,
        "extraction": {"algorithm": "css", "selector": "#x"},
        "fingerprint": {},
    }


def test_validate_source_spec_returns_ok_for_valid_root():
    ok, errs = validate_source_spec(_root_doc())
    assert ok is True
    assert errs == []


def test_validate_source_spec_returns_ok_for_valid_fragment():
    ok, errs = validate_source_spec(_fragment_doc())
    assert ok is True
    assert errs == []


def test_validate_source_spec_returns_structured_errors():
    bad = {"schema_version": 1, "extraction": {"algorithm": "css"}, "fingerprint": {}}
    ok, errs = validate_source_spec(bad)
    assert ok is False
    assert len(errs) >= 1
    assert all("path" in e and "message" in e for e in errs)
    # CSS algorithm without selector → at least one error mentions selector
    assert any("selector" in e["message"].lower() or "/extraction" in e["path"] for e in errs)


def test_validate_root_requires_target_url():
    """validate_root_source_spec rejects a fragment-shaped doc."""
    ok, errs = validate_root_source_spec(_fragment_doc())
    assert ok is False
    assert any(e["path"] == "/target/url" for e in errs)


def test_validate_root_passes_for_valid_root():
    ok, errs = validate_root_source_spec(_root_doc())
    assert ok is True
    assert errs == []


def test_validate_fragment_passes_for_valid_fragment():
    ok, errs = validate_fragment_source_spec(_fragment_doc())
    assert ok is True
    assert errs == []


def test_validate_fragment_rejects_doc_with_target_url():
    """validate_fragment_source_spec rejects a root-shaped doc.

    Fragments must not carry target.url — the parent owns the URL.
    """
    ok, errs = validate_fragment_source_spec(_root_doc())
    assert ok is False
    assert any(e["path"] == "/target/url" for e in errs)


def test_validate_fragment_rejects_doc_with_target_block_even_without_url():
    """A target block without url is also rejected — fragments have no target at all."""
    doc = {
        "schema_version": 1,
        "target": {},
        "extraction": {"algorithm": "css", "selector": "#x"},
        "fingerprint": {},
    }
    ok, errs = validate_fragment_source_spec(doc)
    assert ok is False


def test_validate_source_spec_rejects_extra_property():
    bad = {
        "schema_version": 1,
        "target": {"url": "https://example.com/p"},
        "extraction": {"algorithm": "full_page"},
        "fingerprint": {},
        "junk": True,
    }
    ok, errs = validate_source_spec(bad)
    assert ok is False
