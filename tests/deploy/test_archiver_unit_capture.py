"""``archiver.service`` and the capture switch (archiver#380).

The unit is the only place ``ARCHIVER_CAPTURE_ENABLED`` may be set. Slice A
shipped dark (#493); the flip set it here, so the first click can go to
CannObserv/broker#116's read-back. Rollback re-comments the line and redeploys.
"""

import re
from pathlib import Path

REPO_UNIT = Path(__file__).resolve().parents[2] / "deploy" / "archiver.service"
FLAG = "ARCHIVER_CAPTURE_ENABLED"


def test_the_unit_sets_the_switch_once() -> None:
    active = [
        line.strip()
        for line in REPO_UNIT.read_text().splitlines()
        if re.match(rf"\s*Environment=.*\b{FLAG}=", line)
    ]
    assert active == [f"Environment={FLAG}=1"]


def test_the_unit_no_longer_carries_the_commented_line() -> None:
    assert f"#Environment={FLAG}" not in REPO_UNIT.read_text()
