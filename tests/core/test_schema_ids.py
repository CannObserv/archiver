"""Every authored-document schema carries an org-owned ``$id`` (archiver#373 item 1, D1).

The ``$id`` is an identifier, not a URL anything fetches: no ``$ref`` resolves it
and no route serves it. It stays hierarchical so relative ``$ref``s remain
possible later. ``watcher.exe.xyz`` was a released service's host and never
Archiver's to name.
"""

import json
from pathlib import Path

import pytest

CORE = Path(__file__).resolve().parents[2] / "src" / "core"
BASE = "https://cannabis.observer/schemas/archiver"

EXPECTED_IDS = {
    "source_spec_schema/v1.json": f"{BASE}/source-spec/v1.json",
    "watch_spec_schema/v1.json": f"{BASE}/watch-spec/v1.json",
    "rep_fields_schema/v1.json": f"{BASE}/rep-fields/v1.json",
    "rep_spec_schema/v1.json": f"{BASE}/rep-spec/v1.json",
    "rep_spec_schema/providers/gcs/v1.json": f"{BASE}/rep-spec/providers/gcs/v1.json",
    "rep_spec_schema/providers/gdrive/v1.json": f"{BASE}/rep-spec/providers/gdrive/v1.json",
    "rep_spec_schema/providers/ia/v1.json": f"{BASE}/rep-spec/providers/ia/v1.json",
}


def _schema_files() -> list[Path]:
    return sorted(p for p in CORE.glob("*_schema/**/*.json"))


def test_every_schema_file_is_pinned():
    """A new schema file must be added here, so its ``$id`` is chosen, not inherited."""
    found = {str(p.relative_to(CORE)) for p in _schema_files()}
    assert found == set(EXPECTED_IDS)


@pytest.mark.parametrize("rel,expected", sorted(EXPECTED_IDS.items()))
def test_schema_id_is_org_owned(rel, expected):
    assert json.loads((CORE / rel).read_text())["$id"] == expected


def test_no_watcher_host_under_core_schemas():
    hits = [str(p) for p in _schema_files() if "watcher.exe.xyz" in p.read_text()]
    assert hits == []
