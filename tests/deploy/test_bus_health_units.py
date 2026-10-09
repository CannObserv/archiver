"""The bus-health timer units must exist, carry their guards, and stay in sync.

Same failure class as ``test_installed_unit_matches_repo``: the deployed thing
quietly diverging from the documented thing. Both units are asserted for
content in the repo copy (runs everywhere) and for byte-parity against
``/etc/systemd/system/`` against the live release's copy (skips on hosts that do
not run the timer, or are not cut over yet; archiver#330).
"""

from pathlib import Path

import pytest

from tests.deploy.live_release import drift_message, installed_and_expected

_DEPLOY = Path(__file__).resolve().parents[2] / "deploy"
REPO_SERVICE = _DEPLOY / "archiver-bus-health.service"
REPO_TIMER = _DEPLOY / "archiver-bus-health.timer"


def test_service_is_a_oneshot_probe() -> None:
    text = REPO_SERVICE.read_text()
    assert "Type=oneshot" in text
    assert "src.core.bus_health" in text


def test_service_probes_only_the_outbox() -> None:
    """archiver#193 Phase 3 reduced this unit to archiver's half of the old
    combined probe. The broker-side checks moved to CannObserv/broker with the
    host they measure (D6), and with them the two things this unit needed to
    run them: a ``--state-file`` for the two-tick XPENDING rule, and a
    ``StateDirectory`` to hold it. Either reappearing means the reduction was
    partially reverted - which would leave the unit measuring archiver's disk
    and calling it the broker's AOF headroom, the exact drift D6 exists to
    stop.

    Keyed on the directives rather than the substrings, for the same reason as
    the consumer-group test below: the comment block names both precisely to
    say they are gone, and a substring test would forbid saying so.
    """
    lines = REPO_SERVICE.read_text().splitlines()
    (execstart,) = [ln for ln in lines if ln.startswith("ExecStart=")]
    assert "--state-file" not in execstart
    assert not [ln for ln in lines if ln.startswith("StateDirectory=")]


def test_service_declares_the_production_opt_in() -> None:
    """The probe reads ``changes_outbox`` from the production database, so it
    needs the same unit-scoped opt-in as ``archiver.service`` - in the unit,
    never in an env file, or the hole reopens for every process that sources
    them.

    Since archiver#193 Phase 3 that database read is the *whole* of this unit's
    blast radius, so this is the only guard on it."""
    text = REPO_SERVICE.read_text()
    assert "Environment=ARCHIVER_ALLOW_PRODUCTION_DB=1" in text


def test_service_never_joins_a_consumer_group() -> None:
    """XPENDING is read-only introspection; setting ARCHIVER_BUS_CONSUMER in
    this unit would let the probe silently swallow revisions (archiver#139).
    The unit may (and does) mention the variable in a comment saying exactly
    that - only an Environment= assignment is the hazard."""
    assert "Environment=ARCHIVER_BUS_CONSUMER" not in REPO_SERVICE.read_text()


def test_service_bounds_its_own_runtime() -> None:
    """Originally sized against ~25 bounded Redis calls per tick (CR round 2,
    finding 10). Those calls are gone, but the backstop is not decoration: the
    tick is now a single database query, and asyncpg's connect has no default
    timeout, so a Postgres that hangs rather than refuses would hold the unit
    open indefinitely. A tick that cannot finish inside the bound has nothing
    useful left to report, and being visibly killed beats hanging."""
    text = REPO_SERVICE.read_text()
    assert "TimeoutStartSec=" in text
    (line,) = [ln for ln in text.splitlines() if ln.startswith("TimeoutStartSec=")]
    assert int(line.split("=", 1)[1].rstrip("s")) < 90


def test_timer_ticks_periodically() -> None:
    text = REPO_TIMER.read_text()
    assert "OnUnitActiveSec=" in text
    assert "OnBootSec=" in text


@pytest.mark.parametrize("name", ["archiver-bus-health.service", "archiver-bus-health.timer"])
def test_installed_unit_matches_the_live_release(name: str) -> None:
    """archiver#330 D12: what a host should hold is the live release's copy."""
    installed, expected = installed_and_expected(name)
    assert installed == expected, drift_message(name)
