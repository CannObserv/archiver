"""The production read role's grants, as code (archiver#348).

The real role (``exedev``) exists only on the VM, and ``archiver_agent`` cannot
create roles, so these tests grant to ``PUBLIC`` in a transaction they roll
back and read the result out of the catalogs' ACLs. ``tests/deploy`` checks the
real role on the host.
"""

import re

import pytest
from sqlalchemy import text

from src.core import reader_grants
from src.core.models import Base
from src.core.reader_grants import (
    RESTRICTED,
    SCHEMA,
    apply_grants,
    grant_statements,
    main,
    role_exists,
)

# A column whose name looks like personal data or a credential.
_SENSITIVE = re.compile(r"email|external_id|_hash$|secret|token|password|credential(?!s_alias)")


def _tables() -> dict[str, list[str]]:
    return {
        table.name: [column.name for column in table.columns]
        for table in Base.metadata.tables.values()
        if table.schema == SCHEMA
    }


# --- the classification (pure) ---


def test_every_column_of_a_restricted_table_is_classified():
    """A column added to a restricted table must be named readable or withheld."""
    tables = _tables()
    for name, restriction in RESTRICTED.items():
        assert set(restriction.readable) | set(restriction.withheld) == set(tables[name]), name
        assert not set(restriction.readable) & set(restriction.withheld), name


def test_a_sensitive_looking_column_is_withheld():
    tables = _tables()
    for name, columns in tables.items():
        for column in columns:
            if _SENSITIVE.search(column):
                assert name in RESTRICTED, f"{name}.{column} is readable: restrict {name}"
                assert column in RESTRICTED[name].withheld, f"{name}.{column}"


def test_the_withheld_columns_are_the_ones_348_names():
    assert RESTRICTED["app_users"].withheld == ("external_id", "email")
    assert RESTRICTED["api_keys"].withheld == ("key_hash",)


def test_a_role_name_that_is_not_an_identifier_is_refused():
    with pytest.raises(ValueError, match="role"):
        grant_statements("archiver", "x; DROP TABLE y; --")


def test_the_sql_form_is_one_transaction():
    sql = grant_statements("archiver")
    assert sql[0] == "BEGIN" and sql[-1] == "COMMIT"


# --- against the test database, granted to PUBLIC and rolled back ---


async def _table_grants(conn) -> dict[str, set[str]]:
    rows = await conn.execute(
        text(
            "SELECT c.relname, a.privilege_type FROM pg_class c"
            " JOIN pg_namespace n ON n.oid = c.relnamespace,"
            " aclexplode(c.relacl) a"
            " WHERE n.nspname = :s AND c.relkind = 'r' AND a.grantee = 0"
        ),
        {"s": SCHEMA},
    )
    grants: dict[str, set[str]] = {}
    for table, privilege in rows:
        grants.setdefault(table, set()).add(privilege)
    return grants


async def _column_grants(conn, table: str) -> set[str]:
    rows = await conn.execute(
        text(
            "SELECT att.attname FROM pg_attribute att, aclexplode(att.attacl) a"
            " WHERE att.attrelid = to_regclass(:t) AND a.grantee = 0"
            "   AND a.privilege_type = 'SELECT'"
        ),
        {"t": f"{SCHEMA}.{table}"},
    )
    return {name for (name,) in rows}


async def _default_grants(conn) -> set[str]:
    rows = await conn.execute(
        text(
            "SELECT d.defaclobjtype::text || ':' || a.privilege_type FROM pg_default_acl d,"
            " aclexplode(d.defaclacl) a"
            " WHERE d.defaclnamespace = to_regnamespace(:s) AND a.grantee = 0"
        ),
        {"s": SCHEMA},
    )
    return {row for (row,) in rows}


@pytest.fixture
async def granted(test_engine):
    async with test_engine.connect() as conn:
        await conn.begin()
        try:
            await apply_grants(conn, "PUBLIC")
            yield conn
        finally:
            await conn.rollback()


@pytest.mark.asyncio
async def test_every_unrestricted_table_is_readable_and_only_readable(granted):
    grants = await _table_grants(granted)
    for name in set(_tables()) - set(RESTRICTED):
        assert grants.get(name) == {"SELECT"}, name
    assert grants.get("alembic_version") == {"SELECT"}


@pytest.mark.asyncio
async def test_a_restricted_table_is_readable_by_column_only(granted):
    grants = await _table_grants(granted)
    for name, restriction in RESTRICTED.items():
        assert name not in grants, name
        assert await _column_grants(granted, name) == set(restriction.readable), name


@pytest.mark.asyncio
async def test_a_table_level_grant_on_a_restricted_table_is_undone(test_engine):
    """A migration that recreates one, under default privileges, grants the whole table."""
    async with test_engine.connect() as conn:
        await conn.begin()
        try:
            await conn.execute(text(f"GRANT SELECT ON {SCHEMA}.app_users TO PUBLIC"))
            await apply_grants(conn, "PUBLIC")
            assert "app_users" not in await _table_grants(conn)
            assert "email" not in await _column_grants(conn, "app_users")
        finally:
            await conn.rollback()


@pytest.mark.asyncio
async def test_a_table_created_later_is_readable_by_default(granted):
    assert await _default_grants(granted) == {"r:SELECT"}
    await granted.execute(text(f"CREATE TABLE {SCHEMA}.later_348 (id int)"))
    assert (await _table_grants(granted)).get("later_348") == {"SELECT"}


@pytest.mark.asyncio
async def test_applying_twice_changes_nothing(granted):
    before = (await _table_grants(granted), await _column_grants(granted, "api_keys"))
    await apply_grants(granted, "PUBLIC")
    assert (await _table_grants(granted), await _column_grants(granted, "api_keys")) == before


@pytest.mark.asyncio
async def test_an_absent_role_is_reported_absent(test_engine):
    async with test_engine.connect() as conn:
        assert await role_exists(conn, "no_such_role_348") is False
        # The connecting role, not a named one: CI connects as postgres (CR 8).
        me = (await conn.execute(text("SELECT current_user"))).scalar()
        assert await role_exists(conn, me) is True


# --- the CLI ---


def test_the_cli_does_nothing_for_an_absent_role(monkeypatch, capsys):
    monkeypatch.setattr(reader_grants, "READER_ROLE", "no_such_role_348")
    assert main([]) == 0
    assert "no_such_role_348 absent" in capsys.readouterr().out


def test_the_cli_refuses_production_without_the_opt_in(monkeypatch, capsys):
    monkeypatch.setenv("ARCHIVER_DATABASE_URL", "postgresql+asyncpg://a:b@127.0.0.1:1/archiver")
    monkeypatch.delenv("ARCHIVER_ALLOW_PRODUCTION_DB", raising=False)
    assert main([]) == 2
    assert "reader_grants:" in capsys.readouterr().err


def test_the_sql_form_connects_to_nothing(monkeypatch, capsys):
    monkeypatch.setenv("ARCHIVER_DATABASE_URL", "postgresql+asyncpg://a:b@127.0.0.1:1/archiver")
    assert main(["--sql", "--database", "archiver"]) == 0
    out = capsys.readouterr().out
    assert "GRANT CONNECT ON DATABASE archiver TO exedev;" in out
    assert "REVOKE SELECT ON information.app_users FROM exedev;" in out
