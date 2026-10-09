"""The schema check: the database's Alembic revision against the code's head (archiver#330 D3).

Ported from CannObserv/status R8. ``deploy.sh`` reads it before migrating
(skipping the migration when the database is ``ahead`` - a rollback), the
outbox probe WARNs on ``behind``/``unmigrated``, and nothing refuses a start.
"""

import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from src.core import schema_state
from src.core.db_safety import ALLOW_PRODUCTION_DB_ENV
from src.core.schema_state import (
    EXIT_BEHIND,
    EXIT_ERROR,
    EXIT_OK,
    MultipleHeadsError,
    SchemaState,
    classify,
    code_head,
    database_revision,
    known_revisions,
)

HEAD = "c0de0000head"
OLDER = "c0de0000old1"
KNOWN = frozenset({HEAD, OLDER})


# --- classify (pure) ---


def test_the_head_is_current():
    assert classify(HEAD, head=HEAD, known=KNOWN) is SchemaState.CURRENT


def test_a_revision_the_code_knows_but_is_not_head_is_behind():
    assert classify(OLDER, head=HEAD, known=KNOWN) is SchemaState.BEHIND


def test_a_revision_the_code_does_not_know_is_ahead():
    """What a rollback looks like: older code, newer schema."""
    assert classify("f00000newer1", head=HEAD, known=KNOWN) is SchemaState.AHEAD


def test_no_revision_is_unmigrated():
    assert classify(None, head=HEAD, known=KNOWN) is SchemaState.UNMIGRATED


@pytest.mark.parametrize(
    ("state", "ok"),
    [
        (SchemaState.CURRENT, True),
        (SchemaState.AHEAD, True),
        (SchemaState.BEHIND, False),
        (SchemaState.UNMIGRATED, False),
    ],
)
def test_only_current_and_ahead_can_serve(state, ok):
    assert state.can_serve is ok


# --- the code side ---


def test_code_head_is_the_single_head_of_the_repo_chain():
    head = code_head()
    assert head in known_revisions()
    assert len(head) >= 12


def test_more_than_one_head_is_refused():
    script = SimpleNamespace(get_heads=lambda: ["aaaa", "bbbb"])
    with pytest.raises(MultipleHeadsError, match="aaaa"):
        code_head(script)


# --- the database side ---


async def test_the_migrated_test_database_reads_as_the_code_head(test_engine):
    async with test_engine.connect() as conn:
        rev = await database_revision(conn)
    assert classify(rev, head=code_head(), known=known_revisions()) is SchemaState.CURRENT


async def test_a_missing_version_table_reads_as_no_revision(test_engine):
    """``to_regclass`` probe: the query never aborts the transaction."""
    async with test_engine.connect() as conn:
        assert await database_revision(conn, schema="no_such_schema") is None
        assert (await conn.execute(text("SELECT 1"))).scalar() == 1


# --- the CLI ---


def _run_main(capsys, argv=None) -> tuple[int, str, str]:
    code = schema_state.main(argv or [])
    out, err = capsys.readouterr()
    return code, out, err


@pytest.mark.parametrize(
    ("state", "code"),
    [
        (SchemaState.CURRENT, EXIT_OK),
        (SchemaState.AHEAD, EXIT_OK),
        (SchemaState.BEHIND, EXIT_BEHIND),
        (SchemaState.UNMIGRATED, EXIT_BEHIND),
    ],
)
def test_the_cli_prints_the_state_first_and_maps_it_to_an_exit_code(
    monkeypatch, capsys, state, code
):
    async def fake_probe(url):
        return state, "dbrev", "codehead"

    monkeypatch.setattr(schema_state, "probe", fake_probe)
    got, out, _ = _run_main(capsys)
    assert got == code
    assert out.split()[0] == state.value


def test_the_cli_refuses_an_un_opted_in_production_database_with_exit_2(monkeypatch, capsys):
    monkeypatch.setenv("ARCHIVER_DATABASE_URL", "postgresql+asyncpg://u:p@127.0.0.1:1/archiver")
    monkeypatch.delenv(ALLOW_PRODUCTION_DB_ENV, raising=False)
    got, out, err = _run_main(capsys)
    assert got == EXIT_ERROR
    assert out == ""
    assert "refusing" in err


def test_an_unreachable_database_is_exit_2_never_1(monkeypatch, capsys):
    monkeypatch.setenv("ARCHIVER_DATABASE_URL", "postgresql+asyncpg://u:p@127.0.0.1:1/archiver_dev")
    got, out, err = _run_main(capsys)
    assert got == EXIT_ERROR
    assert out == ""
    assert err


async def test_the_cli_reads_the_real_test_database_as_current(test_engine, capsys):
    """In a thread: ``main`` calls ``asyncio.run`` itself."""
    code = await asyncio.get_running_loop().run_in_executor(None, schema_state.main, [])
    out, _ = capsys.readouterr()
    assert (code, out.split()[0]) == (EXIT_OK, "current")


async def test_the_probe_bounds_its_connect(monkeypatch):
    """CR 6: asyncpg waits 60 s by default; a hung Postgres would stall a deploy."""
    seen = {}

    class Stop(Exception):
        pass

    def fake_engine(url, **kwargs):
        seen.update(kwargs)
        raise Stop

    monkeypatch.setattr(schema_state, "create_async_engine", fake_engine)
    with pytest.raises(Stop):
        await schema_state.probe("postgresql+asyncpg://u:p@127.0.0.1:1/archiver_dev")
    assert seen["connect_args"] == {"timeout": schema_state.CONNECT_TIMEOUT_SECONDS}
    assert schema_state.CONNECT_TIMEOUT_SECONDS <= 10
