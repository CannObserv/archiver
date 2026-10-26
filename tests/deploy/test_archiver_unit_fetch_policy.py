"""``archiver.service`` and the content.fetch-policy flag (archiver#366, #438).

The unit is the only place ``ARCHIVER_FETCH_POLICY_PRODUCER`` may be set. Flip F1
(archiver#438) set it there, once Watcher's producer had stopped
(CannObserv/watcher#374): one producer at a time, and no ACL refuses a second
(CannObserv/broker#93).
"""

import re
from pathlib import Path

REPO_UNIT = Path(__file__).resolve().parents[2] / "deploy" / "archiver.service"
FLAG = "ARCHIVER_FETCH_POLICY_PRODUCER"


def test_the_unit_sets_the_producer_flag_once() -> None:
    active = [
        line.strip()
        for line in REPO_UNIT.read_text().splitlines()
        if re.match(rf"\s*Environment=.*\b{FLAG}=", line)
    ]
    assert active == [f"Environment={FLAG}=1"]


def test_the_unit_no_longer_carries_the_commented_line() -> None:
    assert f"#Environment={FLAG}" not in REPO_UNIT.read_text()
