"""``archiver.service`` alone reads the processor bucket, as its own principal (archiver#367, D4).

The key is a systemd credential, ``LoadCredential=processor-text-reader:...``,
**with** an empty ``SetCredential=`` fallback (the Status key's pattern): a
missing key starts the service with every diff unavailable, and ``deploy.sh``'s
preflight passes it. The bucket is the unit's own ``Environment=`` line. Never
``GOOGLE_APPLICATION_CREDENTIALS`` here: that would make the identity ambient for
every GCS call the process makes. The link origin is the unit's line too.
"""

from pathlib import Path

import pytest

from src.core.notifications.diff_loader import BUCKET_ENV, CREDENTIAL_FILE, CREDENTIAL_NAME
from src.core.public_base_url import PUBLIC_BASE_URL_ENV
from tests.deploy.test_archiver_unit_liveness import _values

DEPLOY = Path(__file__).resolve().parents[2] / "deploy"
OTHER_UNITS = sorted(p for p in DEPLOY.glob("*.service") if p.name != "archiver.service")


def test_the_key_is_a_credential_with_the_empty_fallback() -> None:
    assert f"{CREDENTIAL_NAME}:{CREDENTIAL_FILE}" in _values("Service", "LoadCredential")
    assert f"{CREDENTIAL_NAME}:\\n" in _values("Service", "SetCredential")


def test_the_bucket_is_the_processors() -> None:
    assert f"{BUCKET_ENV}=co-gcs-processor" in _values("Service", "Environment")


def test_links_point_at_the_dashboards_origin() -> None:
    assert f"{PUBLIC_BASE_URL_ENV}=https://co-registrar.exe.xyz" in _values(
        "Service", "Environment"
    )


def test_no_ambient_google_credential() -> None:
    environment = _values("Service", "Environment")
    assert not [v for v in environment if v.startswith("GOOGLE_APPLICATION_CREDENTIALS")]


@pytest.mark.parametrize("unit", OTHER_UNITS, ids=[p.name for p in OTHER_UNITS])
def test_no_other_unit_reads_the_processor_bucket(unit: Path) -> None:
    text = unit.read_text()
    assert CREDENTIAL_NAME not in text
    assert BUCKET_ENV not in text
