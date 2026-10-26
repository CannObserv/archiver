"""``archiver.service`` and the content.fetch-policy flag (archiver#366).

The unit is the only place ``ARCHIVER_FETCH_POLICY_PRODUCER`` may be set, and
until flip F1 it is not set there either: a second producer beside Watcher's is
nothing an ACL refuses (CannObserv/broker#93). The F1 PR flips the first test.
"""

import re
from pathlib import Path

REPO_UNIT = Path(__file__).resolve().parents[2] / "deploy" / "archiver.service"
FLAG = "ARCHIVER_FETCH_POLICY_PRODUCER"


def test_the_unit_keeps_the_producer_dark_until_f1() -> None:
    active = [
        line
        for line in REPO_UNIT.read_text().splitlines()
        if re.match(rf"\s*Environment=.*\b{FLAG}=", line)
    ]
    assert active == [], "F1 is a deliberate PR (docs/BUS.md, the F1 runbook), not a drive-by"


def test_the_unit_carries_the_line_f1_uncomments() -> None:
    assert f"#Environment={FLAG}=1" in REPO_UNIT.read_text()
