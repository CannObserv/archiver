"""``archiver.service`` alone holds the Notifier credential and its gate (archiver#368).

Operator decision D1: the production key is a systemd credential,
``LoadCredential=notifier-key:/etc/archiver/notifier.key``, with **no**
``SetCredential=`` fallback. A missing key fails the start (243/CREDENTIALS):
notifying is this unit's job, so a lost key must be loud. ``deploy.sh`` refuses a
deploy to a host without the file (``TestUnitCredentials``). The URL and the flag
are the unit's own ``Environment=`` lines. Never ``/etc/archiver/.env``: three
timer units load that file whole.
"""

from pathlib import Path

import pytest

from src.core.notifier.gate import BASE_URL_ENV, CREDENTIAL_FILE, CREDENTIAL_NAME, ENABLED_ENV
from tests.deploy.test_archiver_unit_liveness import _values

DEPLOY = Path(__file__).resolve().parents[2] / "deploy"
OTHER_UNITS = sorted(p for p in DEPLOY.glob("*.service") if p.name != "archiver.service")


def test_the_key_is_a_credential_with_no_fallback() -> None:
    assert f"{CREDENTIAL_NAME}:{CREDENTIAL_FILE}" in _values("Service", "LoadCredential")
    assert not [v for v in _values("Service", "SetCredential") if v.startswith(CREDENTIAL_NAME)]


def test_the_url_and_the_flag_are_the_units_own_lines() -> None:
    environment = _values("Service", "Environment")
    assert f"{BASE_URL_ENV}=http://notifier:9000" in environment
    assert f"{ENABLED_ENV}=1" in environment


def test_the_key_is_never_an_environment_line() -> None:
    text = (DEPLOY / "archiver.service").read_text()
    assert "ARCHIVER_NOTIFIER_API_KEY" not in text


def test_the_others_are_listed() -> None:
    """The units the brief names: a glob that matched nothing would pass vacuously."""
    assert {p.stem for p in OTHER_UNITS} >= {
        "archiver-bus-health",
        "archiver-pm-org-refresh",
        "archiver-temporal-boundary",
        "archiver-drift",
        "archiver-backup",
    }


@pytest.mark.parametrize("unit", OTHER_UNITS, ids=[p.name for p in OTHER_UNITS])
def test_no_other_unit_holds_notifier_config(unit: Path) -> None:
    text = unit.read_text()
    assert "NOTIFIER" not in text.upper()
    assert CREDENTIAL_NAME not in text
