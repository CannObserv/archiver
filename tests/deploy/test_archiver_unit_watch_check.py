"""``archiver.service`` and the check-now switch (archiver#370 D6, #482).

The unit is the only place ``ARCHIVER_WATCH_CHECK_ENABLED`` may be set. Flip F4
(archiver#482) set it there, after the operator's go was recorded on
CannObserv/watcher#368. Rollback re-comments the line and redeploys.
"""

import re
from pathlib import Path

REPO_UNIT = Path(__file__).resolve().parents[2] / "deploy" / "archiver.service"
FLAG = "ARCHIVER_WATCH_CHECK_ENABLED"


def test_the_unit_sets_the_switch_once() -> None:
    active = [
        line.strip()
        for line in REPO_UNIT.read_text().splitlines()
        if re.match(rf"\s*Environment=.*\b{FLAG}=", line)
    ]
    assert active == [f"Environment={FLAG}=1"]


def test_the_unit_no_longer_carries_the_commented_line() -> None:
    assert f"#Environment={FLAG}" not in REPO_UNIT.read_text()
