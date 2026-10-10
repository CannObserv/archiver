"""The drift check's timer units (archiver#338): content, isolation, parity.

Modelled on ``test_pm_org_refresh_units``: the repo copy is asserted everywhere,
byte-parity of ``/etc/systemd/system/`` with the live release's copy only where
the timer is installed and the host is cut over (archiver#330).
"""

from pathlib import Path

import pytest

from src.core.drift import CHECK_TIMEOUT_SECONDS, MONITOR_ID_ENV, MONITOR_ID_PATTERN
from src.core.status_checkin import CREDENTIAL_NAME
from tests.deploy.live_release import drift_message, installed_and_expected

_DEPLOY = Path(__file__).resolve().parents[2] / "deploy"
REPO_SERVICE = _DEPLOY / "archiver-drift.service"
REPO_TIMER = _DEPLOY / "archiver-drift.timer"
#: co-archiver-drift, tenant co-archiver (CannObserv/status#32 comment 6101304752).
MONITOR_ID = "01M4KMDDN3XWJR0GCECTAYMVTV"


def _directives(path: Path, key: str) -> list[str]:
    return [ln.split("=", 1)[1] for ln in path.read_text().splitlines() if ln.startswith(f"{key}=")]


def test_service_is_a_oneshot_running_the_check_from_the_release() -> None:
    assert _directives(REPO_SERVICE, "Type") == ["oneshot"]
    assert _directives(REPO_SERVICE, "WorkingDirectory") == ["/srv/archiver/live"]
    (execstart,) = _directives(REPO_SERVICE, "ExecStart")
    assert execstart == "/srv/archiver/live/.venv/bin/python -m src.core.drift"


def test_service_names_the_monitor() -> None:
    assert f"{MONITOR_ID_ENV}={MONITOR_ID}" in _directives(REPO_SERVICE, "Environment")
    assert MONITOR_ID_PATTERN.fullmatch(MONITOR_ID)


def test_service_reads_no_env_file() -> None:
    """``/etc/archiver/.env`` holds the database and Power Map credentials, which
    a drift check has no use for: only the Status key, as a credential."""
    assert _directives(REPO_SERVICE, "EnvironmentFile") == []


def test_service_gets_the_key_as_a_credential_with_an_empty_fallback() -> None:
    assert _directives(REPO_SERVICE, "LoadCredential") == [
        f"{CREDENTIAL_NAME}:/etc/archiver/status-checkin.key"
    ]
    assert _directives(REPO_SERVICE, "SetCredential") == [f"{CREDENTIAL_NAME}:\\n"]


@pytest.mark.parametrize("name", ["ARCHIVER_ALLOW_PRODUCTION_DB", "ARCHIVER_BUS_CONSUMER"])
def test_service_holds_no_production_opt_in(name: str) -> None:
    assert not [v for v in _directives(REPO_SERVICE, "Environment") if v.startswith(name)]


def test_service_hard_stop_outlasts_the_github_deadline() -> None:
    """No GitHub call starts past 60 s, each bounded at 10 s, then one 10 s check-in."""
    (value,) = _directives(REPO_SERVICE, "TimeoutStartSec")
    assert CHECK_TIMEOUT_SECONDS + 10 + 10 <= int(value) < 3600


def test_service_has_no_retry_loop() -> None:
    """The next hour is the retry; the monitor's grace absorbs one missed run."""
    assert _directives(REPO_SERVICE, "Restart") == []


def test_service_waits_for_the_tailnet() -> None:
    """Status is reached by its MagicDNS name, ``status``."""
    (after,) = _directives(REPO_SERVICE, "After")
    assert "tailscaled.service" in after.split()


SANDBOX = ["NoNewPrivileges=yes", "PrivateTmp=yes", "ProtectSystem=strict", "ProtectHome=yes"]


@pytest.mark.parametrize("directive", SANDBOX)
def test_service_is_sandboxed(directive: str) -> None:
    """It reads one file under the release and talks HTTPS: nothing else."""
    assert directive in REPO_SERVICE.read_text().splitlines()


def test_timer_ticks_hourly() -> None:
    """co-archiver-drift expects a check-in every 3600 s, grace 5400 s (status#32)."""
    assert _directives(REPO_TIMER, "OnUnitActiveSec") == ["1h"]
    assert _directives(REPO_TIMER, "OnBootSec")
    assert _directives(REPO_TIMER, "Unit") == ["archiver-drift.service"]


@pytest.mark.parametrize("name", ["archiver-drift.service", "archiver-drift.timer"])
def test_installed_unit_matches_the_live_release(name: str) -> None:
    """archiver#330 D12: what a host should hold is the live release's copy."""
    installed, expected = installed_and_expected(name)
    assert installed == expected, drift_message(name)
