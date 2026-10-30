"""The lifespan's processor-text reader and link base (archiver#367, D4).

One reader per process, built after the gates and closed at shutdown, from the
unit's ``processor-text-reader`` credential. **Degrade, don't refuse**: a
missing or empty key leaves every diff unavailable and logs one WARNING; the
service still starts. The lifespan makes no GCS request. It also says, once,
which origin links point at, or that there is none.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from src.api import main
from src.api.main import app, lifespan
from src.core.notifications import diff_loader
from src.core.notifications.diff_loader import BUCKET_ENV, CREDENTIAL_NAME
from src.core.public_base_url import PUBLIC_BASE_URL_ENV
from tests.core.notifications.builders import FakeStorage

KEY = {"type": "service_account", "client_email": "reader@co-test.iam.gserviceaccount.com"}


@pytest.fixture(autouse=True)
def _no_bus(monkeypatch):
    monkeypatch.delenv("ARCHIVER_REDIS_URL", raising=False)


async def test_unconfigured_starts_without_a_reader(test_engine, caplog) -> None:
    with caplog.at_level(logging.INFO):
        async with lifespan(app):
            assert app.state.text_reader is None
    assert not [
        r for r in caplog.records if r.levelno >= logging.WARNING and "text" in r.getMessage()
    ]


async def test_a_bucket_without_a_key_warns_once_and_still_serves(
    monkeypatch, tmp_path: Path, test_engine, caplog
) -> None:
    """``SetCredential=processor-text-reader:\\n``: the unit's fallback, an empty key."""
    (tmp_path / CREDENTIAL_NAME).write_text("\n")
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(tmp_path))
    monkeypatch.setenv(BUCKET_ENV, "co-gcs-processor")
    with caplog.at_level(logging.WARNING):
        async with lifespan(app):
            assert app.state.text_reader is None
    (warning,) = [r for r in caplog.records if "processor text" in r.getMessage()]
    assert warning.levelno == logging.WARNING
    assert "change diffs are unavailable" in warning.getMessage()


async def test_the_unit_shape_builds_one_reader_and_closes_it(
    monkeypatch, tmp_path: Path, test_engine, caplog
) -> None:
    storage = FakeStorage()
    monkeypatch.setattr(diff_loader, "_storage_client", lambda *, info: storage)
    (tmp_path / CREDENTIAL_NAME).write_text(json.dumps(KEY))
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(tmp_path))
    monkeypatch.setenv(BUCKET_ENV, "co-gcs-processor")
    with caplog.at_level(logging.INFO):
        async with lifespan(app):
            assert app.state.text_reader.bucket == "co-gcs-processor"
            assert storage.gets == []  # no request at startup
    assert storage.closed
    assert "processor text reader configured (bucket co-gcs-processor)" in caplog.text
    assert KEY["client_email"] not in caplog.text


@pytest.mark.parametrize(
    ("value", "said"),
    [
        ("https://co-registrar.exe.xyz", "links point at https://co-registrar.exe.xyz"),
        (None, "no links"),
        ("https://co-registrar.exe.xyz/dashboard", "no links"),
    ],
)
async def test_the_link_base_is_announced(monkeypatch, test_engine, caplog, value, said) -> None:
    if value is None:
        monkeypatch.delenv(PUBLIC_BASE_URL_ENV, raising=False)
    else:
        monkeypatch.setenv(PUBLIC_BASE_URL_ENV, value)
    with caplog.at_level(logging.INFO, logger=main.__name__):
        async with lifespan(app):
            pass
    assert said in caplog.text
