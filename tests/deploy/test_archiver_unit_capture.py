"""``archiver.service`` and the capture switch (archiver#380 slice A).

The unit is the only place ``ARCHIVER_CAPTURE_ENABLED`` may be set. Slice A
ships dark: the line is present and commented. The flip uncomments it in its own
change; the first click then goes to CannObserv/broker#116's read-back.
"""

import re
from pathlib import Path

REPO_UNIT = Path(__file__).resolve().parents[2] / "deploy" / "archiver.service"
FLAG = "ARCHIVER_CAPTURE_ENABLED"


def test_the_unit_does_not_set_the_switch_yet() -> None:
    active = [
        line.strip()
        for line in REPO_UNIT.read_text().splitlines()
        if re.match(rf"\s*Environment=.*\b{FLAG}=", line)
    ]
    assert active == []


def test_the_unit_carries_the_commented_line_for_the_flip() -> None:
    assert f"#Environment={FLAG}=1" in REPO_UNIT.read_text()
