"""The production read role on this host (archiver#348).

Agents read production as role ``exedev`` over the Unix socket, peer-
authenticated, with no password anywhere. These tests connect exactly as an
agent does - ``psql -d archiver`` with no ``PG*`` variables - and prove the
properties the role claims: it reads, it cannot write even with the session's
read-only default switched off, the withheld columns stay withheld, and the
limits are in place. A host without the role (CI, a VM before the runbook)
skips; any other failure to connect is an error, not a skip.
"""

import os
import shutil
import subprocess

import pytest

from src.core.reader_grants import READER_ROLE, RESTRICTED, SCHEMA

SOCKET_DIR = "/var/run/postgresql"
DATABASE = "archiver"


def psql(sql: str) -> subprocess.CompletedProcess:
    """One statement list as an agent would run it: socket, OS user, no password."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("PG")}
    return subprocess.run(
        ["psql", "-X", "-At", "-v", "ON_ERROR_STOP=1", "-h", SOCKET_DIR, "-d", DATABASE, "-c", sql],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


@pytest.fixture(scope="module", autouse=True)
def reader():
    if shutil.which("psql") is None:
        pytest.skip("no psql on this host")
    if not os.path.exists(f"{SOCKET_DIR}/.s.PGSQL.5432"):
        pytest.skip("no Postgres socket on this host")
    probe = psql("SELECT current_user")
    if f'role "{READER_ROLE}" does not exist' in probe.stderr:
        pytest.skip(f"no {READER_ROLE} role on this host (docs/plans/2026-10-11-348-*)")
    assert probe.returncode == 0, probe.stderr
    assert probe.stdout.strip() == READER_ROLE


def denied(result: subprocess.CompletedProcess) -> bool:
    return result.returncode != 0 and "permission denied" in result.stderr


def test_it_reads_the_registry():
    result = psql(f"SELECT count(*) FROM {SCHEMA}.info_items")
    assert result.returncode == 0, result.stderr


def test_it_reads_the_schema_revision():
    result = psql(f"SELECT version_num FROM {SCHEMA}.alembic_version")
    assert result.returncode == 0 and result.stdout.strip(), result.stderr


# Each statement runs with the read-only default switched off first, so what
# refuses it is the missing privilege, not the session setting (#348 req. 1).
@pytest.mark.parametrize(
    "statement",
    [
        f"INSERT INTO {SCHEMA}.domains (id, name) VALUES ('x', 'example.invalid')",
        f"UPDATE {SCHEMA}.info_items SET name = name WHERE false",
        f"DELETE FROM {SCHEMA}.changes_outbox WHERE false",
        f"TRUNCATE {SCHEMA}.watch_status",
        f"CREATE TABLE {SCHEMA}.reader_348 (id int)",
        "CREATE TABLE public.reader_348 (id int)",
        "CREATE TEMP TABLE reader_348 (id int)",
    ],
    ids=["insert", "update", "delete", "truncate", "ddl", "ddl-public", "temp"],
)
def test_it_cannot_write_even_with_read_only_off(statement):
    result = psql(f"SET default_transaction_read_only = off; {statement}")
    assert denied(result), result.stderr


def test_it_cannot_become_the_owner():
    assert denied(psql("SET ROLE archiver"))


@pytest.mark.parametrize(
    ("table", "column"),
    [(table, column) for table, r in RESTRICTED.items() for column in r.withheld],
)
def test_a_withheld_column_is_denied(table, column):
    assert denied(psql(f"SELECT {column} FROM {SCHEMA}.{table} LIMIT 0"))


@pytest.mark.parametrize("table", list(RESTRICTED))
def test_a_restricted_table_reads_its_allowlist_but_not_star(table):
    columns = ", ".join(RESTRICTED[table].readable)
    allowed = psql(f"SELECT {columns} FROM {SCHEMA}.{table} LIMIT 0")
    assert allowed.returncode == 0, allowed.stderr
    assert denied(psql(f"SELECT * FROM {SCHEMA}.{table} LIMIT 0"))


def test_the_limits_are_set():
    result = psql(
        "SELECT rolconnlimit FROM pg_roles WHERE rolname = current_user;"
        " SHOW statement_timeout; SHOW idle_in_transaction_session_timeout;"
        " SHOW default_transaction_read_only; SHOW log_statement"
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["3", "30s", "1min", "on", "all"]


def test_it_sees_other_sessions_queries():
    """``pg_read_all_stats``: lock debugging needs ``pg_stat_activity.query``."""
    result = psql("SELECT pg_has_role('pg_read_all_stats', 'member')")
    assert result.stdout.strip() == "t", result.stderr
