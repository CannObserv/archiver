"""``archiver.service``'s liveness and restart settings (archiver#297).

The service checks in to ``co-archiver-live`` while its bus loops progress, and
Status pages on the silence. The unit supplies the monitor id and the key, and
bounds restarts so that a crash loop ends ``failed`` (and silent) rather than
restarting forever. There is no ``OnFailure=``: silence is the page.
"""

import configparser
import sys
from pathlib import Path

import pytest

from src.core.liveness import MONITOR_ID_ENV
from src.core.status_checkin import CREDENTIAL_NAME, MONITOR_ID_PATTERN

REPO_UNIT = Path(__file__).resolve().parents[2] / "deploy" / "archiver.service"
#: co-archiver-live, tenant co-archiver (CannObserv/status#47 issuecomment-6221210998).
MONITOR_ID = "01M52WN2A5SVMK2B4ZZ4RD2TDD"


def _sections() -> dict[str, list[tuple[str, str]]]:
    """Each section's directives in order; repeats kept, which configparser drops."""
    sections: dict[str, list[tuple[str, str]]] = {}
    current = ""
    for line in REPO_UNIT.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1]
            sections.setdefault(current, [])
            continue
        key, _, value = line.partition("=")
        sections[current].append((key.strip(), value.strip()))
    return sections


def _values(section: str, key: str) -> list[str]:
    return [v for k, v in _sections().get(section, []) if k == key]


def test_the_unit_parses() -> None:
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    parser.read_string(REPO_UNIT.read_text())
    assert {"Unit", "Service", "Install"} <= set(parser.sections())


@pytest.mark.parametrize(
    ("key", "value"), [("StartLimitIntervalSec", "300"), ("StartLimitBurst", "5")]
)
def test_restarts_are_bounded_in_the_unit_section(key: str, value: str) -> None:
    """5 starts in 300 s: with ``RestartSec=5`` a crash loop ends ``failed`` in
    about 30 s. Without them the default (5 in 10 s) can never be spent at 5 s
    apart, and a crash loop restarts forever. ``[Unit]`` is their home since
    systemd 230; the ``[Service]`` spelling is legacy, so one place only."""
    assert _values("Unit", key) == [value]
    assert _values("Service", key) == []


def test_restart_policy_is_unchanged() -> None:
    assert _values("Service", "Restart") == ["on-failure"]
    assert _values("Service", "RestartSec") == ["5"]


def test_no_on_failure_handler() -> None:
    """Out of scope by decision (archiver#297): the heartbeat's silence pages."""
    assert not [
        k for section in _sections().values() for k, _ in section if k.startswith("OnFailure")
    ]


def test_the_key_is_a_credential_with_an_empty_fallback() -> None:
    """Without the fallback a missing key fails the start (243/CREDENTIALS), and
    ``deploy.sh`` switches back: the service must run unmonitored instead."""
    assert [v for v in _values("Service", "LoadCredential") if v.startswith(CREDENTIAL_NAME)] == [
        f"{CREDENTIAL_NAME}:/etc/archiver/status-checkin.key"
    ]
    assert [v for v in _values("Service", "SetCredential") if v.startswith(CREDENTIAL_NAME)] == [
        f"{CREDENTIAL_NAME}:\\n"
    ]


def test_the_unit_names_the_monitor() -> None:
    assert MONITOR_ID_PATTERN.fullmatch(MONITOR_ID)
    assert f"{MONITOR_ID_ENV}={MONITOR_ID}" in _values("Service", "Environment")


def test_a_planned_stop_is_clean_by_systemds_own_rule() -> None:
    """uvicorn re-raises the SIGTERM it shut down on, and systemd counts death by
    SIGTERM as clean for any type but oneshot: the stop ends ``inactive``. Under
    ``uv run`` the same stop was exit code 143 and ended ``failed`` (archiver#297;
    the process half is ``test_planned_stop``). So: no ``SuccessExitStatus=``,
    and never ``uv run``."""
    assert _values("Service", "Type") == ["simple"]
    assert _values("Service", "SuccessExitStatus") == []
    (execstart,) = _values("Service", "ExecStart")
    assert execstart.startswith("/srv/archiver/live/.venv/bin/uvicorn ")
    assert "uv run" not in execstart


def test_the_parser_reads_spaced_directives(tmp_path, monkeypatch) -> None:
    """systemd accepts ``Key = value``: a pin blind to it passes on the edit it guards."""
    unit = tmp_path / "spaced.service"
    unit.write_text("[Unit]\nStartLimitBurst = 5\n[Service]\nSuccessExitStatus = 143\n")
    monkeypatch.setattr(sys.modules[__name__], "REPO_UNIT", unit)
    assert _values("Unit", "StartLimitBurst") == ["5"]
    assert _values("Service", "SuccessExitStatus") == ["143"]
