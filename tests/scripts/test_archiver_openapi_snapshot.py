"""Freshness gate: ``clients/python/archiver-openapi.json`` matches the in-repo app.

The CI ``client-drift`` gate is hermetic — it regenerates the SDK from the
committed snapshot and diffs against the committed tree. That catches a
hand-edited tree, but a skipped regen after a ``src/api`` change leaves the
snapshot and the tree *consistently* stale, and the hermetic gate passes
(the failure mode behind the v4.1 ``/domains`` hole, archiver#92).

Unlike watcher, archiver's app lives in this repo, so freshness is testable
offline: re-derive the canonical spec exactly as ``scripts/dump_openapi.py``
does and compare byte-for-byte with the committed snapshot.
"""

import json
from pathlib import Path

from src.api.main import app

_SNAPSHOT = Path(__file__).resolve().parents[2] / "clients" / "python" / "archiver-openapi.json"


def test_archiver_openapi_snapshot_matches_app() -> None:
    """A src/api change without a client regen must fail the suite."""
    canonical = json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"
    assert _SNAPSHOT.read_text() == canonical, (
        "clients/python/archiver-openapi.json is stale vs the in-repo app. "
        "Run clients/python/scripts/regen.sh and commit the refreshed "
        "snapshot + generated tree."
    )
