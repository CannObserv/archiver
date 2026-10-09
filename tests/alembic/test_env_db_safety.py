"""``alembic/env.py`` refuses an un-opted-in production database (archiver#330 D9).

Before #330, any shell that had sourced ``/etc/archiver/.env`` could run
``alembic upgrade`` or ``downgrade`` against production, and CLAUDE.md told
agents to. Once production runs releases, ``scripts/deploy.sh`` is the one
sanctioned migrator: it alone passes ``ARCHIVER_ALLOW_PRODUCTION_DB=1`` to
alembic. ``--sql`` (offline) runs connect to nothing and are not checked
(status#15).
"""

import io
from pathlib import Path

import pytest
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig

from src.core.db_safety import ALLOW_PRODUCTION_DB_ENV, ProductionDatabaseRefused

_INI = Path(__file__).resolve().parents[2] / "alembic.ini"

# Port 1 on loopback: nothing listens, so an attempt to connect fails fast with
# a connection error - distinguishable from the guard's refusal.
_PROD_URL = "postgresql+asyncpg://archiver:pw@127.0.0.1:1/archiver"


def _config() -> AlembicConfig:
    return AlembicConfig(str(_INI), stdout=io.StringIO())


def test_online_upgrade_refuses_production_without_the_opt_in(monkeypatch):
    monkeypatch.setenv("ARCHIVER_DATABASE_URL", _PROD_URL)
    monkeypatch.delenv(ALLOW_PRODUCTION_DB_ENV, raising=False)

    with pytest.raises(ProductionDatabaseRefused, match="scripts/deploy.sh"):
        alembic_command.upgrade(_config(), "head")


def test_online_downgrade_is_refused_too(monkeypatch):
    monkeypatch.setenv("ARCHIVER_DATABASE_URL", _PROD_URL)
    monkeypatch.delenv(ALLOW_PRODUCTION_DB_ENV, raising=False)

    with pytest.raises(ProductionDatabaseRefused):
        alembic_command.downgrade(_config(), "-1")


def test_the_opt_in_lets_alembic_reach_the_database(monkeypatch):
    """With the flag the guard passes, and the run fails only on connecting."""
    monkeypatch.setenv("ARCHIVER_DATABASE_URL", _PROD_URL)
    monkeypatch.setenv(ALLOW_PRODUCTION_DB_ENV, "1")

    with pytest.raises(OSError):
        alembic_command.upgrade(_config(), "head")


def test_an_offline_sql_run_is_not_checked(monkeypatch):
    """Only the first revision: later data migrations read rows, which ``--sql`` cannot."""
    monkeypatch.setenv("ARCHIVER_DATABASE_URL", _PROD_URL)
    monkeypatch.delenv(ALLOW_PRODUCTION_DB_ENV, raising=False)

    alembic_command.upgrade(_config(), "base:d8899e01cbd0", sql=True)
