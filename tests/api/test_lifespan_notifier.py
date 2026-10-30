"""The lifespan's Notifier gate (archiver#368): refuse, dormant, or one client.

The gate is judged before any resource is built, and a refusal is logged at
CRITICAL before it propagates, so the journal shows the actionable text rather
than a traceback. The lifespan makes **no** Notifier call: an outage must not stop
the registry. Notifier is respx here (``respx_mock`` refuses every unmocked
request), so a startup call would fail the test.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from src.api import main
from src.api.main import app, lifespan
from src.core.notifier.client import Notifier
from src.core.notifier.gate import (
    API_KEY_ENV,
    BASE_URL_ENV,
    CREDENTIAL_NAME,
    ENABLED_ENV,
    NotifierCredentialMissing,
    NotifierNotEnabled,
)

KEY = "nk_test-0123456789abcdef"


@pytest.fixture(autouse=True)
def _no_bus(monkeypatch):
    monkeypatch.delenv("ARCHIVER_REDIS_URL", raising=False)


async def test_dormant_starts_with_no_client(test_engine, respx_mock) -> None:
    async with lifespan(app):
        assert app.state.notifier is None


async def test_the_unit_shape_builds_one_client_and_calls_nothing(
    monkeypatch, tmp_path: Path, test_engine, respx_mock, caplog
) -> None:
    (tmp_path / CREDENTIAL_NAME).write_text(f"{KEY}\n")
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(tmp_path))
    monkeypatch.setenv(BASE_URL_ENV, "http://notifier.test:9000")
    monkeypatch.setenv(ENABLED_ENV, "1")
    with caplog.at_level(logging.INFO):
        async with lifespan(app):
            client = app.state.notifier
            assert isinstance(client, Notifier)
            assert client.key_source == "credential"
    assert not respx_mock.calls
    assert client._client._http.is_closed
    assert "Notifier configured at http://notifier.test:9000 (key: credential)" in caplog.text
    assert KEY not in caplog.text


@pytest.mark.parametrize(
    ("environ", "refusal"),
    [
        ({BASE_URL_ENV: "http://notifier.test:9001", API_KEY_ENV: KEY}, NotifierNotEnabled),
        ({ENABLED_ENV: "1"}, NotifierCredentialMissing),
        ({ENABLED_ENV: "1", BASE_URL_ENV: "http://notifier.test:9000"}, NotifierCredentialMissing),
    ],
)
async def test_a_half_configuration_refuses_startup_loudly(
    monkeypatch, test_engine, caplog, environ, refusal
) -> None:
    for name, value in environ.items():
        monkeypatch.setenv(name, value)
    with caplog.at_level(logging.CRITICAL, logger="src.api.main"), pytest.raises(refusal):
        async with lifespan(app):
            pytest.fail("the lifespan served with a refused Notifier configuration")
    (record,) = [r for r in caplog.records if r.levelno == logging.CRITICAL]
    assert record.getMessage().startswith("Notifier: refusing to start: ")
    assert KEY not in caplog.text


async def test_a_setup_failure_after_the_gate_builds_no_client(
    monkeypatch, tmp_path: Path, test_engine, respx_mock
) -> None:
    """The gate is judged first, the client built last before serving (CR 5): a
    failure in between can't leave an httpx pool unclosed."""
    (tmp_path / CREDENTIAL_NAME).write_text(f"{KEY}\n")
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(tmp_path))
    monkeypatch.setenv(BASE_URL_ENV, "http://notifier.test:9000")
    monkeypatch.setenv(ENABLED_ENV, "1")
    built: list[object] = []
    monkeypatch.setattr(main, "Notifier", lambda config: built.append(config))

    def _broken() -> None:
        raise RuntimeError("setup failed")

    monkeypatch.setattr(main, "AsyncFetchDriver", _broken)
    with pytest.raises(RuntimeError, match="setup failed"):
        async with lifespan(app):
            pytest.fail("served")
    assert built == []
