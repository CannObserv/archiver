"""The Power Map org follower's timer units (archiver#305): content, gating, parity.

Modelled on ``test_bus_health_units``: the repo copy is asserted everywhere,
byte-parity of ``/etc/systemd/system/`` with the live release's copy only where
the timer is installed and the host is cut over (archiver#330).
"""

from pathlib import Path

import pytest

from tests.deploy.live_release import drift_message, installed_and_expected

_DEPLOY = Path(__file__).resolve().parents[2] / "deploy"
REPO_SERVICE = _DEPLOY / "archiver-pm-org-refresh.service"
REPO_TIMER = _DEPLOY / "archiver-pm-org-refresh.timer"


def _directives(path: Path, key: str) -> list[str]:
    return [ln.split("=", 1)[1] for ln in path.read_text().splitlines() if ln.startswith(f"{key}=")]


def test_service_is_a_oneshot_running_the_follower() -> None:
    assert _directives(REPO_SERVICE, "Type") == ["oneshot"]
    (execstart,) = _directives(REPO_SERVICE, "ExecStart")
    assert execstart.endswith("python -m src.core.tools.refresh_orgs")


def test_service_loads_the_production_env_file() -> None:
    """The Power Map key lives in ``/etc/archiver/.env``; without it the
    follower is dormant and silently refreshes nothing."""
    assert "/etc/archiver/.env" in _directives(REPO_SERVICE, "EnvironmentFile")


def test_service_declares_the_production_opt_in() -> None:
    """The follower writes ``pm_organizations`` and ``info_items`` on the
    production database: the unit-scoped opt-in, never an env file's."""
    assert "ARCHIVER_ALLOW_PRODUCTION_DB=1" in _directives(REPO_SERVICE, "Environment")


def test_service_never_joins_a_consumer_group() -> None:
    assert not [
        v for v in _directives(REPO_SERVICE, "Environment") if v.startswith("ARCHIVER_BUS_CONSUMER")
    ]


def test_service_bounds_its_own_runtime() -> None:
    """Paced at 2 req/s, a sweep is linear in linked orgs; the bound stays
    well inside the hourly cadence so two sweeps never overlap."""
    (value,) = _directives(REPO_SERVICE, "TimeoutStartSec")
    assert 0 < int(value.rstrip("s")) < 3600


def test_timer_ticks_hourly() -> None:
    assert _directives(REPO_TIMER, "OnUnitActiveSec") == ["1h"]
    assert _directives(REPO_TIMER, "OnBootSec")


@pytest.mark.parametrize(
    "name", ["archiver-pm-org-refresh.service", "archiver-pm-org-refresh.timer"]
)
def test_installed_unit_matches_the_live_release(name: str) -> None:
    """archiver#330 D12: what a host should hold is the live release's copy."""
    installed, expected = installed_and_expected(name)
    assert installed == expected, drift_message(name)
