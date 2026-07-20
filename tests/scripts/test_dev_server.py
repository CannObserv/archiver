"""Tests for ``scripts/dev_server.sh``.

The dev server (port 8021) previously had no launch script — CLAUDE.md
documented a raw ``uvicorn`` recipe that sourced ``/etc/archiver/.env`` and
therefore inherited ``ARCHIVER_DATABASE_URL`` pointing at **production**. A
dashboard verification run on 2026-07-18 drove that dev server and wrote a
``verify79.example.com`` Domain, two InfoSources, and an AppUser into the
production database.

``scripts/dev_server.sh`` closes that hole: it resolves a non-production
database URL, refuses to start if the resolution lands on production, and only
then execs uvicorn. This mirrors ``_check_test_url_safety`` in
``tests/conftest.py``, which protects pytest but not a hand-run server.

``ARCHIVER_DEV_SERVER_DRY_RUN=1`` makes the script print its resolution and
exit before exec'ing uvicorn, so the guard is testable without binding a port.
"""

import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "dev_server.sh"

PROD_URL = "postgresql+asyncpg://archiver:archiver@localhost:5432/archiver"
TEST_URL = "postgresql+asyncpg://archiver:archiver@localhost:5432/archiver_test"
DEV_URL = "postgresql+asyncpg://archiver:archiver@localhost:5432/archiver_dev"


def run(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Invoke the script in dry-run mode with a hermetic environment.

    ``ARCHIVER_DEV_SERVER_SKIP_ENV_FILES`` stops the script sourcing the real
    ``/etc/archiver/.env`` and ``.env``, so tests control resolution entirely.
    """
    return subprocess.run(
        ["bash", str(SCRIPT)],
        env={
            "PATH": "/usr/bin:/bin",
            "ARCHIVER_DEV_SERVER_DRY_RUN": "1",
            "ARCHIVER_DEV_SERVER_SKIP_ENV_FILES": "1",
            **env,
        },
        text=True,
        capture_output=True,
    )


def test_resolves_to_test_database_by_default() -> None:
    """With only TEST_DATABASE_URL set, the dev server targets the test DB."""
    result = run({"TEST_DATABASE_URL": TEST_URL, "ARCHIVER_DATABASE_URL": PROD_URL})
    assert result.returncode == 0, result.stderr
    assert f"ARCHIVER_DATABASE_URL={TEST_URL}" in result.stdout


def test_dedicated_dev_url_wins_over_test_url() -> None:
    """ARCHIVER_DEV_DATABASE_URL takes precedence when both are set.

    Lets an operator keep a persistent dev database that pytest's
    DROP SCHEMA teardown will not wipe out from under a running dev server.
    """
    result = run(
        {
            "ARCHIVER_DEV_DATABASE_URL": DEV_URL,
            "TEST_DATABASE_URL": TEST_URL,
            "ARCHIVER_DATABASE_URL": PROD_URL,
        }
    )
    assert result.returncode == 0, result.stderr
    assert f"ARCHIVER_DATABASE_URL={DEV_URL}" in result.stdout


@pytest.mark.parametrize("prod_var", ["ARCHIVER_DATABASE_URL", "DATABASE_URL"])
def test_refuses_when_resolution_equals_production(prod_var: str) -> None:
    """The exact 2026-07-18 failure: dev server resolving onto production."""
    result = run({prod_var: PROD_URL, "TEST_DATABASE_URL": PROD_URL})
    assert result.returncode != 0
    assert prod_var in result.stderr
    assert "production" in result.stderr.lower()


def test_refuses_when_no_non_production_url_is_available() -> None:
    """Absent a dev/test URL the script must fail, never fall back to prod."""
    result = run({"ARCHIVER_DATABASE_URL": PROD_URL})
    assert result.returncode != 0
    assert "TEST_DATABASE_URL" in result.stderr


def test_clears_inherited_database_url_fallback() -> None:
    """DATABASE_URL must not survive into the child environment.

    ``src/api/deps`` falls back to ``DATABASE_URL`` when
    ``ARCHIVER_DATABASE_URL`` is unset; leaving a production value in place
    would let the fallback re-introduce the very leak this guard prevents.
    """
    result = run({"DATABASE_URL": PROD_URL, "TEST_DATABASE_URL": TEST_URL})
    assert result.returncode == 0, result.stderr
    assert "DATABASE_URL=(cleared)" in result.stdout


def test_refuses_to_bind_the_production_port() -> None:
    """Port 8020 belongs to systemd; a dev launch there is always a mistake."""
    result = run({"TEST_DATABASE_URL": TEST_URL, "ARCHIVER_DEV_PORT": "8020"})
    assert result.returncode != 0
    assert "8020" in result.stderr


def test_reports_planned_migration_of_the_dev_database() -> None:
    """The script migrates the dev DB before serving.

    pytest teardown runs DROP SCHEMA information CASCADE against
    TEST_DATABASE_URL, so a dev server pointed there routinely starts against
    a schema-less database and 500s on every write. An operator who hits that
    is one step from reaching for the old prod-pointing recipe, so the launch
    path has to leave the dev database usable on its own.
    """
    result = run({"TEST_DATABASE_URL": TEST_URL})
    assert result.returncode == 0, result.stderr
    assert f"MIGRATE={TEST_URL}" in result.stdout


def test_migration_can_be_skipped() -> None:
    """ARCHIVER_DEV_SKIP_MIGRATE=1 leaves the dev schema untouched."""
    result = run({"TEST_DATABASE_URL": TEST_URL, "ARCHIVER_DEV_SKIP_MIGRATE": "1"})
    assert result.returncode == 0, result.stderr
    assert "MIGRATE=(skipped)" in result.stdout
