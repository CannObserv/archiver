"""The lifespan's capture image reader (archiver#380 slice D, D4).

One reader per process, built after the gates and closed at shutdown, from the
unit's ``capture-reader`` credential. Degrade, don't refuse: no credential is
dormant; an empty one (the unit's fallback) logs one WARNING and the card shows
metadata only. The lifespan makes no GCS request.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from src.api.main import app, lifespan
from src.core import capture_reader
from src.core.capture_reader import CREDENTIAL_NAME
from tests.core.test_capture_reader import FakeStorage

KEY = {"type": "service_account", "client_email": "captures@co-test.iam.gserviceaccount.com"}


@pytest.fixture(autouse=True)
def _no_bus(monkeypatch):
    monkeypatch.delenv("ARCHIVER_REDIS_URL", raising=False)
    monkeypatch.delenv("CREDENTIALS_DIRECTORY", raising=False)


async def test_unconfigured_starts_without_a_reader(test_engine, caplog) -> None:
    with caplog.at_level(logging.INFO):
        async with lifespan(app):
            assert app.state.capture_reader is None
    assert not [
        r for r in caplog.records if r.levelno >= logging.WARNING and "capture" in r.getMessage()
    ]


async def test_the_empty_fallback_warns_once_and_still_serves(
    monkeypatch, tmp_path: Path, test_engine, caplog
) -> None:
    (tmp_path / CREDENTIAL_NAME).write_text("\n")
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(tmp_path))
    with caplog.at_level(logging.WARNING):
        async with lifespan(app):
            assert app.state.capture_reader is None
    (warning,) = [r for r in caplog.records if "capture image reader" in r.getMessage()]
    assert warning.levelno == logging.WARNING


async def test_the_unit_shape_builds_one_reader_and_closes_it(
    monkeypatch, tmp_path: Path, test_engine, caplog
) -> None:
    storage = FakeStorage()
    monkeypatch.setattr(capture_reader, "_storage_client", lambda *, info: storage)
    (tmp_path / CREDENTIAL_NAME).write_text(json.dumps(KEY))
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(tmp_path))
    with caplog.at_level(logging.INFO):
        async with lifespan(app):
            assert app.state.capture_reader is not None
            assert capture_reader.bound() is app.state.capture_reader
            assert storage.gets == []  # no request at startup
    assert storage.closed
    assert capture_reader.bound() is None
    assert "capture image reader configured (bucket co-gcs-captures)" in caplog.text
    assert KEY["client_email"] not in caplog.text
