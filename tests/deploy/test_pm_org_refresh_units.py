"""The Power Map org follower's timer units (archiver#305): content, gating, parity.

Modelled on ``test_bus_health_units``: the repo copy is asserted everywhere,
byte-parity against ``/etc/systemd/system/`` only where the timer is installed.
"""

from pathlib import Path

import pytest

_DEPLOY = Path(__file__).resolve().parents[2] / "deploy"
REPO_SERVICE = _DEPLOY / "archiver-pm-org-refresh.service"
REPO_TIMER = _DEPLOY / "archiver-pm-org-refresh.timer"
INSTALLED_SERVICE = Path("/etc/systemd/system/archiver-pm-org-refresh.service")
INSTALLED_TIMER = Path("/etc/systemd/system/archiver-pm-org-refresh.timer")


def _read_if_installed(path: Path) -> str | None:
    """Only ``FileNotFoundError`` means "not installed"; anything else propagates."""
    try:
        return path.read_text()
    except FileNotFoundError:
        return None


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
    ("repo", "installed"), [(REPO_SERVICE, INSTALLED_SERVICE), (REPO_TIMER, INSTALLED_TIMER)]
)
def test_installed_unit_matches_repo(repo: Path, installed: Path) -> None:
    text = _read_if_installed(installed)
    if text is None:
        pytest.skip(f"{installed} not present - not a host running the timer")
    assert text == repo.read_text(), (
        f"{installed} has drifted from {repo}.\n"
        "Reinstall with:\n"
        f"  sudo cp {repo} {installed} && sudo systemctl daemon-reload"
    )
