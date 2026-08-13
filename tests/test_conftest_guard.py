"""Unit tests for the conftest production-URL safety guard."""

import os

import pytest

from tests.conftest import _OUTBOUND_SERVICE_ENV_VARS, _check_test_url_safety


def test_guard_raises_when_test_url_matches_archiver_database_url(monkeypatch):
    monkeypatch.setenv("ARCHIVER_DATABASE_URL", "postgresql+asyncpg://host/prod_archiver")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="must not equal ARCHIVER_DATABASE_URL"):
        _check_test_url_safety("postgresql+asyncpg://host/prod_archiver")


def test_guard_raises_when_test_url_matches_database_url(monkeypatch):
    monkeypatch.delenv("ARCHIVER_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://host/prod_archiver")
    with pytest.raises(RuntimeError, match="must not equal DATABASE_URL"):
        _check_test_url_safety("postgresql+asyncpg://host/prod_archiver")


def test_guard_raises_on_archiver_database_url_even_when_database_url_differs(monkeypatch):
    monkeypatch.setenv("ARCHIVER_DATABASE_URL", "postgresql+asyncpg://host/prod_archiver")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://host/other_db")
    with pytest.raises(RuntimeError, match="must not equal ARCHIVER_DATABASE_URL"):
        _check_test_url_safety("postgresql+asyncpg://host/prod_archiver")


def test_guard_passes_when_test_url_differs_from_both(monkeypatch):
    monkeypatch.setenv("ARCHIVER_DATABASE_URL", "postgresql+asyncpg://host/prod_archiver")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://host/other_db")
    _check_test_url_safety("postgresql+asyncpg://host/archiver_test")  # no exception


def test_guard_passes_when_no_prod_urls_set(monkeypatch):
    monkeypatch.delenv("ARCHIVER_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    _check_test_url_safety("postgresql+asyncpg://host/archiver_test")  # no exception


def test_outbound_service_env_is_scrubbed():
    """The test process must never hold a live outbound-service address (#157).

    On 2026-08-13 a suite run with /etc/archiver/.env sourced provisioned 108
    real WatchedItems into production watcher: the ``client`` fixture runs the
    full app lifespan, the lifespan built a real WatcherClient from
    WATCHER_BASE_URL/WATCHER_API_KEY, and provisioning routes made real POSTs —
    HTTP side effects, so the savepoint fixture that keeps the DB and (it turned
    out) the bus clean could not contain them. Same failure class as
    watcher#233: a test process silently inheriting a production resource from a
    sourced env file.

    conftest scrubs the whole outbound surface at import, before any fixture
    runs. A test that needs one of these sets it explicitly via monkeypatch —
    which is also why this test asserting absence stays correct: monkeypatch
    restores on teardown.
    """
    for var in _OUTBOUND_SERVICE_ENV_VARS:
        assert var not in os.environ, (
            f"{var} leaked into the test process — the conftest scrub is the only "
            f"thing between a test run and production (#157)"
        )
