"""``archiver.service`` and the capture image reader's credential (archiver#380 D4).

Archiver reads capture images from ``co-gcs-captures`` as its own principal,
``archiver-capture-reader`` (``objectViewer`` on that bucket alone). The key is a
systemd credential with the empty ``SetCredential=`` fallback, the
processor-text reader's shape: a missing key starts the service with images
unavailable and one WARNING.

**Flipped** (2026-11-12): the operator provisioned the bucket, the grant and the
key (CannObserv/replicator#189), and a read as the unit's identity was proven
first. Rollback re-comments both lines and redeploys.
"""

import re
from pathlib import Path

import pytest

from src.core.capture_reader import CREDENTIAL_FILE, CREDENTIAL_NAME

DEPLOY = Path(__file__).resolve().parents[2] / "deploy"
REPO_UNIT = DEPLOY / "archiver.service"
OTHER_UNITS = sorted(p for p in DEPLOY.glob("*.service") if p.name != "archiver.service")


def _lines(pattern: str) -> list[str]:
    return [
        line.strip()
        for line in REPO_UNIT.read_text().splitlines()
        if re.match(pattern, line) and CREDENTIAL_NAME in line
    ]


def test_the_credential_is_loaded_with_the_empty_fallback() -> None:
    assert _lines(r"\s*(LoadCredential|SetCredential)=") == [
        f"LoadCredential={CREDENTIAL_NAME}:{CREDENTIAL_FILE}",
        f"SetCredential={CREDENTIAL_NAME}:\\n",
    ]


def test_no_commented_copy_is_left_behind() -> None:
    assert _lines(r"\s*#(LoadCredential|SetCredential)=") == []


@pytest.mark.parametrize("unit", OTHER_UNITS, ids=[p.name for p in OTHER_UNITS])
def test_no_other_unit_reads_the_captures_bucket(unit: Path) -> None:
    assert CREDENTIAL_NAME not in unit.read_text()
