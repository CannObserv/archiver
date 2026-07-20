"""Tests for ``src.core.db_safety`` — the production-database startup guard.

Background (archiver, 2026-07-18 incident): the documented dev-server recipe
sourced ``/etc/archiver/.env`` and ran uvicorn directly, leaving
``ARCHIVER_DATABASE_URL`` pointed at production. The dev server on 8021 and the
live service on 8020 shared one database, and a dashboard verification run
wrote a ``verify79.example.com`` Domain, two InfoSources, and an AppUser into
the production registry.

``scripts/dev_server.sh`` fixes the sanctioned launch path, but a docs-side fix
has the same failure mode as the docs bug it patches — a hand-rolled uvicorn,
or a stale recipe copied from an old plan doc, still reaches production. This
module is the launch-path-independent backstop: the application itself refuses
to serve a production database unless the caller opts in explicitly, which only
the systemd unit does.
"""

import pytest

from src.core.db_safety import (
    ProductionDatabaseRefused,
    assert_production_db_allowed,
    database_name,
    is_non_production_database,
)

PROD = "postgresql+asyncpg://archiver:archiver@localhost:5432/archiver"
TEST = "postgresql+asyncpg://archiver:archiver@localhost:5432/archiver_test"
DEV = "postgresql+asyncpg://archiver:archiver@localhost:5432/archiver_dev"


class TestDatabaseName:
    """URL → database name extraction."""

    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            (PROD, "archiver"),
            (TEST, "archiver_test"),
            ("postgresql://archiver:archiver@localhost:5432/archiver", "archiver"),
            ("postgresql+psycopg://u:p@host:5432/archiver_test", "archiver_test"),
            # No port.
            ("postgresql://u:p@host/archiver", "archiver"),
            # Query string must not bleed into the name.
            ("postgresql://u:p@host:5432/archiver_test?sslmode=require", "archiver_test"),
            # Password containing a slash must not be mistaken for a path.
            ("postgresql://u:p%2Fw@host:5432/archiver", "archiver"),
        ],
    )
    def test_extracts_name(self, url: str, expected: str) -> None:
        assert database_name(url) == expected

    @pytest.mark.parametrize(
        "url", ["", "not-a-url", "postgresql://host:5432/", "postgresql://host"]
    )
    def test_returns_none_when_undeterminable(self, url: str) -> None:
        """An unparseable URL yields None so callers can fail closed."""
        assert database_name(url) is None


class TestIsNonProductionDatabase:
    """Positive assertion — the name must *look* disposable.

    Finding 1 of the CR: comparing the dev URL to the prod URL by string
    equality is defeated by a cosmetic difference (``postgresql://`` vs
    ``postgresql+asyncpg://``, ``localhost`` vs ``127.0.0.1``). Asserting the
    database *name* carries a ``_test``/``_dev`` suffix is not bypassable that
    way, and it matches the convention AGENTS.md already documents.
    """

    @pytest.mark.parametrize(
        "url", [TEST, DEV, "postgresql://h/anything_test", "postgresql://h/x_dev"]
    )
    def test_accepts_test_and_dev_suffixes(self, url: str) -> None:
        assert is_non_production_database(url) is True

    @pytest.mark.parametrize(
        "url",
        [
            PROD,
            "postgresql://h/archiver",
            # Substring, not suffix — must not pass.
            "postgresql://h/test_archiver",
            "postgresql://h/archiver_testing",
            "postgresql://h/devious",
        ],
    )
    def test_rejects_production_looking_names(self, url: str) -> None:
        assert is_non_production_database(url) is False

    def test_unparseable_url_is_treated_as_production(self) -> None:
        """Fail closed: if we cannot read the name, assume it is production."""
        assert is_non_production_database("not-a-url") is False


class TestAssertProductionDbAllowed:
    """The startup gate itself."""

    def test_allows_non_production_database_without_opt_in(self) -> None:
        assert_production_db_allowed(TEST, allow_flag=None)

    def test_refuses_production_database_without_opt_in(self) -> None:
        """The incident condition, from any launch path."""
        with pytest.raises(ProductionDatabaseRefused) as excinfo:
            assert_production_db_allowed(PROD, allow_flag=None)
        message = str(excinfo.value)
        assert "archiver" in message
        assert "ARCHIVER_ALLOW_PRODUCTION_DB" in message

    def test_allows_production_database_with_explicit_opt_in(self) -> None:
        """Only the systemd unit sets this; it is how the live service starts."""
        assert_production_db_allowed(PROD, allow_flag="1")

    @pytest.mark.parametrize("flag", ["0", "", "true", "yes", "no"])
    def test_only_exact_1_opts_in(self, flag: str) -> None:
        """A fuzzy truthiness check would let a stray value re-open the hole."""
        with pytest.raises(ProductionDatabaseRefused):
            assert_production_db_allowed(PROD, allow_flag=flag)

    def test_refuses_unparseable_url_without_opt_in(self) -> None:
        with pytest.raises(ProductionDatabaseRefused):
            assert_production_db_allowed("not-a-url", allow_flag=None)
