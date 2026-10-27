"""The temporal-profile boundary's timer units (archiver#365, D2): content, gating, parity.

Modelled on ``test_pm_org_refresh_units``: the repo copy is asserted everywhere,
byte-parity of ``/etc/systemd/system/`` with the live release's copy only where
the timer is installed and the host is cut over (archiver#330).
"""

from pathlib import Path

import pytest

from tests.deploy.live_release import drift_message, installed_and_expected

_DEPLOY = Path(__file__).resolve().parents[2] / "deploy"
REPO_SERVICE = _DEPLOY / "archiver-temporal-boundary.service"
REPO_TIMER = _DEPLOY / "archiver-temporal-boundary.timer"


def _directives(path: Path, key: str) -> list[str]:
    return [ln.split("=", 1)[1] for ln in path.read_text().splitlines() if ln.startswith(f"{key}=")]


def test_service_is_a_oneshot_running_the_boundary() -> None:
    assert _directives(REPO_SERVICE, "Type") == ["oneshot"]
    (execstart,) = _directives(REPO_SERVICE, "ExecStart")
    assert execstart.endswith("python -m src.core.tools.temporal_boundary")


def test_service_runs_the_live_release_as_the_service_user() -> None:
    assert _directives(REPO_SERVICE, "User") == ["archiver"]
    assert _directives(REPO_SERVICE, "WorkingDirectory") == ["/srv/archiver/live"]
    assert "/etc/archiver/.env" in _directives(REPO_SERVICE, "EnvironmentFile")


def test_service_declares_the_production_opt_in() -> None:
    """The run writes profiles, items and the outbox on the production database:
    the unit-scoped opt-in, never an env file's."""
    assert "ARCHIVER_ALLOW_PRODUCTION_DB=1" in _directives(REPO_SERVICE, "Environment")


def test_service_never_joins_a_consumer_group() -> None:
    assert not [
        v for v in _directives(REPO_SERVICE, "Environment") if v.startswith("ARCHIVER_BUS_CONSUMER")
    ]


def test_service_bounds_its_own_runtime() -> None:
    (value,) = _directives(REPO_SERVICE, "TimeoutStartSec")
    assert 0 < int(value.rstrip("s")) < 3600


def test_timer_runs_daily_after_the_utc_boundary_and_catches_up() -> None:
    """D2: just past 00:00Z, when a profile steps; a missed run catches up."""
    assert _directives(REPO_TIMER, "OnCalendar") == ["*-*-* 00:05:00 UTC"]
    assert _directives(REPO_TIMER, "Persistent") == ["true"]
    assert _directives(REPO_TIMER, "Unit") == ["archiver-temporal-boundary.service"]


@pytest.mark.parametrize(
    "name", ["archiver-temporal-boundary.service", "archiver-temporal-boundary.timer"]
)
def test_installed_unit_matches_the_live_release(name: str) -> None:
    """archiver#330 D12: what a host should hold is the live release's copy."""
    installed, expected = installed_and_expected(name)
    assert installed == expected, drift_message(name)
