"""The installed systemd unit must match the repo copy.

CR finding 13. ``deploy/archiver.service`` gained
``Environment=ARCHIVER_ALLOW_PRODUCTION_DB=1``, without which the service
refuses to start once ``src.core.db_safety`` is deployed. That unit was
installed to ``/etc/systemd/system/`` by hand, and nothing verified it stayed
in sync afterwards.

Which is the same failure class as the incident that started this workstream:
the deployed thing quietly diverging from the documented thing. A future edit
to ``deploy/archiver.service`` that never reaches the VM would either fail to
apply a needed setting or, worse, leave the service unable to start on its
next restart.

Skips when the unit is not installed, so CI and dev clones pass; it only
asserts on a host that actually runs the service. Since archiver#330 the copy a
host should hold is the live release's, which ``scripts/deploy.sh`` installs:
a merged unit edit is not drift until it is deployed, and a difference from the
live release is a hand edit. Before the cutover there is no ``live`` link, and
the test skips.
"""

from pathlib import Path

from tests.deploy.live_release import drift_message, installed_and_expected

REPO_UNIT = Path(__file__).resolve().parents[2] / "deploy" / "archiver.service"


def test_repo_unit_declares_the_production_opt_in() -> None:
    """The opt-in must live in the unit, never in an env file.

    An EnvironmentFile is sourced by every process that loads it — putting the
    flag there would re-open the hole for hand-run servers, which is exactly
    what the guard exists to close.
    """
    text = REPO_UNIT.read_text()
    assert "Environment=ARCHIVER_ALLOW_PRODUCTION_DB=1" in text


def test_installed_unit_matches_the_live_release() -> None:
    installed, expected = installed_and_expected("archiver.service")
    assert installed == expected, drift_message("archiver.service")
