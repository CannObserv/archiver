"""SourceSpec validator wrapper tests."""

from src.core.source_spec_schema.validator import validate_source_spec


def _spec(algorithm: str = "full_page", selector: str | None = None) -> dict:
    doc: dict = {
        "schema_version": 1,
        "extraction": {"algorithm": algorithm},
        "fingerprint": {},
    }
    if selector is not None:
        doc["extraction"]["selector"] = selector
    return doc


def test_validate_source_spec_ok_for_full_page():
    ok, errs = validate_source_spec(_spec("full_page"))
    assert ok is True
    assert errs == []


def test_validate_source_spec_ok_for_css_with_selector():
    ok, errs = validate_source_spec(_spec("css", selector="#x"))
    assert ok is True
    assert errs == []


def test_validate_source_spec_returns_structured_errors():
    bad = {"schema_version": 1, "extraction": {"algorithm": "css"}, "fingerprint": {}}
    ok, errs = validate_source_spec(bad)
    assert ok is False
    assert len(errs) >= 1
    assert all("path" in e and "message" in e for e in errs)
    assert any("selector" in e["message"].lower() or "/extraction" in e["path"] for e in errs)


def test_validate_source_spec_rejects_target_field():
    """target is not part of the spec schema — URL lives on InfoSource."""
    bad = {
        "schema_version": 1,
        "target": {"url": "https://example.com"},
        "extraction": {"algorithm": "full_page"},
        "fingerprint": {},
    }
    ok, errs = validate_source_spec(bad)
    assert ok is False


def test_validate_source_spec_rejects_extra_property():
    bad = {
        "schema_version": 1,
        "extraction": {"algorithm": "full_page"},
        "fingerprint": {},
        "junk": True,
    }
    ok, errs = validate_source_spec(bad)
    assert ok is False
