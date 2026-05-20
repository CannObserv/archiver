"""Unit tests for the conftest production-URL safety guard."""

import pytest

from tests.conftest import _check_test_url_safety


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
