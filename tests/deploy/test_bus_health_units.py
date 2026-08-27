"""The bus-health timer units must exist, carry their guards, and stay in sync.

Same failure class as ``test_installed_unit_matches_repo``: the deployed thing
quietly diverging from the documented thing. Both units are asserted for
content in the repo copy (runs everywhere) and for byte-parity against
``/etc/systemd/system/`` (skips on hosts that do not run the timer).
"""

from pathlib import Path

import pytest

_DEPLOY = Path(__file__).resolve().parents[2] / "deploy"
REPO_SERVICE = _DEPLOY / "archiver-bus-health.service"
REPO_TIMER = _DEPLOY / "archiver-bus-health.timer"
INSTALLED_SERVICE = Path("/etc/systemd/system/archiver-bus-health.service")
INSTALLED_TIMER = Path("/etc/systemd/system/archiver-bus-health.timer")


def _read_if_installed(path: Path) -> str | None:
    """Only ``FileNotFoundError`` means "not installed" - a ``PermissionError``
    propagates rather than silently passing (see the archiver.service test)."""
    try:
        return path.read_text()
    except FileNotFoundError:
        return None


def test_service_is_a_oneshot_probe() -> None:
    text = REPO_SERVICE.read_text()
    assert "Type=oneshot" in text
    assert "src.core.bus_health" in text


def test_service_declares_the_production_opt_in() -> None:
    """The probe reads ``changes_outbox`` from the production database, so it
    needs the same unit-scoped opt-in as ``archiver.service`` - in the unit,
    never in an env file, or the hole reopens for every process that sources
    them."""
    text = REPO_SERVICE.read_text()
    assert "Environment=ARCHIVER_ALLOW_PRODUCTION_DB=1" in text


def test_service_never_joins_a_consumer_group() -> None:
    """XPENDING is read-only introspection; setting ARCHIVER_BUS_CONSUMER in
    this unit would let the probe silently swallow revisions (archiver#139).
    The unit may (and does) mention the variable in a comment saying exactly
    that - only an Environment= assignment is the hazard."""
    assert "Environment=ARCHIVER_BUS_CONSUMER" not in REPO_SERVICE.read_text()


def test_timer_ticks_periodically() -> None:
    text = REPO_TIMER.read_text()
    assert "OnUnitActiveSec=" in text
    assert "OnBootSec=" in text


def test_installed_service_matches_repo() -> None:
    installed = _read_if_installed(INSTALLED_SERVICE)
    if installed is None:
        pytest.skip(f"{INSTALLED_SERVICE} not present - not a host running the timer")
    assert installed == REPO_SERVICE.read_text(), (
        f"{INSTALLED_SERVICE} has drifted from {REPO_SERVICE}.\n"
        "Reinstall with:\n"
        f"  sudo cp {REPO_SERVICE} {INSTALLED_SERVICE} && sudo systemctl daemon-reload"
    )


def test_installed_timer_matches_repo() -> None:
    installed = _read_if_installed(INSTALLED_TIMER)
    if installed is None:
        pytest.skip(f"{INSTALLED_TIMER} not present - not a host running the timer")
    assert installed == REPO_TIMER.read_text(), (
        f"{INSTALLED_TIMER} has drifted from {REPO_TIMER}.\n"
        "Reinstall with:\n"
        f"  sudo cp {REPO_TIMER} {INSTALLED_TIMER} && sudo systemctl daemon-reload"
    )
