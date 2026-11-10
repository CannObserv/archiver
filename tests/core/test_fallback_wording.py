"""Extra SourceSpecs are fallbacks, never cross-checks (archiver#373 item 3, D3).

co-core takes the first spec whose extraction is non-empty
(``co_core/pure/extract/spec_fingerprint.py``); nothing compares the specs'
outputs. The binding role ``cross_check`` (``info_item_sources.role``) is a
different thing and is out of this rule's reach.
"""

import json
from pathlib import Path

from src.api.schemas.info_source import InfoSourceCreate
from src.api.schemas.source_revision import SourceRevisionOut

ROOT = Path(__file__).resolve().parents[2]
WORDING = "the first spec whose extraction is non-empty wins"


def test_source_spec_schema_states_fallback_order():
    desc = json.loads((ROOT / "src/core/source_spec_schema/v1.json").read_text())["description"]
    assert WORDING in desc
    assert "cross-check" not in desc


def test_info_source_create_source_specs_states_fallback_order():
    desc = InfoSourceCreate.model_fields["source_specs"].description
    assert WORDING in desc
    assert "cross-check" not in desc


def test_spec_position_names_a_fallback():
    desc = SourceRevisionOut.model_fields["spec_position"].description
    assert "fallback" in desc
    assert "cross-check" not in desc


def test_no_cross_check_alternative_left_in_code_or_docs():
    paths = [
        *ROOT.joinpath("src").rglob("*.py"),
        *ROOT.joinpath("src").rglob("*.json"),
        ROOT / "clients/python/src/archiver_client/client.py",
        ROOT / "docs/SCHEMA_SOURCES.md",
    ]
    hits = [str(p) for p in paths if "cross-check alternative" in p.read_text()]
    assert hits == []
