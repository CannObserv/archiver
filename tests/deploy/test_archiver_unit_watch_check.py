"""``archiver.service`` and the check-now switch (archiver#370 D6).

The unit is the only place ``ARCHIVER_WATCH_CHECK_ENABLED`` may be set, and #370
ships dark: the line is present but commented. Flip F4 uncomments it - after the
operator's go is recorded on CannObserv/watcher#368 - and rewrites these two
tests to F1's shape (``test_archiver_unit_fetch_policy.py``).
"""

import re
from pathlib import Path

REPO_UNIT = Path(__file__).resolve().parents[2] / "deploy" / "archiver.service"
FLAG = "ARCHIVER_WATCH_CHECK_ENABLED"


def test_the_unit_does_not_set_the_switch_before_f4() -> None:
    active = [
        line.strip()
        for line in REPO_UNIT.read_text().splitlines()
        if re.match(rf"\s*Environment=.*\b{FLAG}=", line)
    ]
    assert active == []


def test_the_unit_carries_the_commented_line_f4_uncomments() -> None:
    commented = [
        line.strip()
        for line in REPO_UNIT.read_text().splitlines()
        if line.strip() == f"#Environment={FLAG}=1"
    ]
    assert commented == [f"#Environment={FLAG}=1"]
