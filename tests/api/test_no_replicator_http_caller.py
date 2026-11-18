"""No route, schema or SDK docstring names Replicator or Watcher as an HTTP caller (#528).

#513 measured that no cohort service calls this host's API: Replicator closes a
replication over the bus (``content.artifacts``), and ``src/core/`` writes
``public_url`` back. A docstring saying otherwise reaches the OpenAPI snapshot
and the generated client, where a reader takes it as the contract.
"""

import json
import re
from pathlib import Path

from src.api.main import app

_SERVICE = r"(?:replicator|watcher)"
_CLAIM = re.compile(
    rf"called by {_SERVICE}|{_SERVICE} callback|{_SERVICE} calls|\(e\.g\. {_SERVICE}\)", re.I
)
_SDK = Path(__file__).resolve().parents[2] / "clients" / "python" / "src" / "archiver_client"


def test_the_openapi_names_no_replicator_caller() -> None:
    """Route and schema docstrings both land in the spec's descriptions."""
    assert not _CLAIM.findall(json.dumps(app.openapi()))


def test_the_hand_written_sdk_names_no_replicator_caller() -> None:
    """``generated/`` derives from the spec above; the wrappers are written by hand."""
    hand_written = [p for p in _SDK.rglob("*.py") if "generated" not in p.parts]
    assert hand_written
    offenders = [str(p.relative_to(_SDK)) for p in hand_written if _CLAIM.search(p.read_text())]
    assert not offenders


def test_the_pattern_catches_each_phrasing() -> None:
    """Non-vacuity: both phrasings #528 found, and CR 5's Watcher example."""
    for text in (
        "Called by Replicator after a successful replication job.",
        "Patch a SourceRevision's cache fields (Replicator callback).",
        "may be supplied by the client (e.g. Watcher) so the scratch file",
    ):
        assert _CLAIM.search(text), text
