"""A real dump, shipped and restored, on every integration run (archiver#233).

broker#4's rule, carried by watcher#296: an untested backup is a second thing to
discover during an incident, so the round trip runs in the suite, not once by
hand. Real ``pg_dump`` / ``psql`` / ``pg_restore`` against two scratch
``*_test`` databases; only the bucket is the SDK-faithful fake.

What no fake can answer: that the dump carries the ``information`` schema whole,
personal-data columns included (the reason the job reads as its own
``pg_read_all_data`` role and not as ``exedev``, whose #348 allowlist withholds
them), and the column-level grants the read role depends on.

Needs ``CREATEDB`` (and ``CREATEROLE`` for the grant check) on the test role:
CI's ``postgres`` has both; this VM's ``archiver_agent`` has neither, and the
module skips there. On CI a missing precondition fails instead.
"""

import os
import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from src.core import backup, restore
from tests.conftest import TEST_DATABASE_URL
from tests.core.gcs_fakes import FakeBucket, FakeClient

pytestmark = pytest.mark.integration

READER_ROLE = "archiver_rehearsal_reader"
BUCKET = "rehearsal-bucket"


def _with_database(url: str, name: str) -> str:
    return re.sub(r"/[^/?]+(\?|$)", f"/{name}\\1", url, count=1)


def _libpq(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://", 1)


def _unavailable(reason: str) -> None:
    """Skip here; fail on CI, where every precondition is provisioned and a
    skip would hide the suite's one real round trip."""
    if os.environ.get("CI"):
        pytest.fail(f"rehearsal cannot run on CI: {reason}")
    pytest.skip(reason)


def _major(version_text: str) -> int:
    return int(re.search(r"(\d+)", version_text).group(1))


@pytest.fixture
async def databases():
    """Two scratch databases on the test server, created and always dropped.

    ``_test``-suffixed so the restore's target guard passes them, and named per
    process so parallel suites cannot collide.
    """
    for binary in ("pg_dump", "pg_restore", "psql"):
        if shutil.which(binary) is None:
            _unavailable(f"{binary} not installed")
    admin = create_async_engine(TEST_DATABASE_URL, isolation_level="AUTOCOMMIT")
    names = (f"archiver_rh{os.getpid()}_src_test", f"archiver_rh{os.getpid()}_dst_test")
    try:
        async with admin.connect() as conn:
            server = int((await conn.execute(text("SHOW server_version_num"))).scalar()) // 10000
            dump_version = subprocess.run(["pg_dump", "--version"], capture_output=True, text=True)
            if _major(dump_version.stdout) < server:
                _unavailable(f"pg_dump is older than the server ({dump_version.stdout.strip()})")
            exists = await conn.execute(
                text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": READER_ROLE}
            )
            if not exists.scalar():
                try:
                    await conn.execute(text(f"CREATE ROLE {READER_ROLE} NOLOGIN"))
                except Exception as exc:  # no CREATEROLE: nothing to rehearse
                    _unavailable(f"{READER_ROLE} absent and cannot be created: {exc}")
            for name in names:
                await conn.execute(text(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)"))
                try:
                    await conn.execute(text(f"CREATE DATABASE {name}"))
                except Exception as exc:  # no CREATEDB: nothing to rehearse
                    _unavailable(f"cannot create scratch databases: {exc}")
        yield tuple(_with_database(TEST_DATABASE_URL, name) for name in names)
    finally:
        async with admin.connect() as conn:
            for name in names:
                await conn.execute(text(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)"))
        await admin.dispose()


def test_on_ci_a_missing_precondition_fails_rather_than_skips(monkeypatch) -> None:
    """CI's server is a superuser and its runner has the client tools, so a
    skip there means the runner image changed: the one real round trip in the
    suite would go quiet while everything stays green."""
    monkeypatch.setenv("CI", "true")
    with pytest.raises(pytest.fail.Exception, match="pg_dump not installed"):
        _unavailable("pg_dump not installed")
    monkeypatch.delenv("CI")
    with pytest.raises(pytest.skip.Exception, match="pg_dump not installed"):
        _unavailable("pg_dump not installed")


SEED = [
    "CREATE SCHEMA information",
    "CREATE TABLE information.alembic_version (version_num varchar(32) PRIMARY KEY)",
    "INSERT INTO information.alembic_version VALUES ('rehearsal01')",
    "CREATE TABLE information.info_items (id bigserial PRIMARY KEY, name text NOT NULL)",
    "INSERT INTO information.info_items (name) SELECT 'item ' || g FROM generate_series(1, 25) g",
    "CREATE TABLE information.app_users (id bigserial PRIMARY KEY, email text NOT NULL)",
    "INSERT INTO information.app_users (email) VALUES ('a@example.com'), ('b@example.com')",
    # The shape src/core/reader_grants.py leaves: a column allowlist, no email.
    f"GRANT USAGE ON SCHEMA information TO {READER_ROLE}",
    f"GRANT SELECT ON information.info_items TO {READER_ROLE}",
    f"GRANT SELECT (id) ON information.app_users TO {READER_ROLE}",
]

CHECKS = {
    "items": "SELECT count(*) FROM information.info_items",
    "emails": "SELECT string_agg(email, ',' ORDER BY id) FROM information.app_users",
    "head": "SELECT version_num FROM information.alembic_version",
    "reads_items": (
        f"SELECT has_table_privilege('{READER_ROLE}', 'information.info_items', 'SELECT')"
    ),
    "reads_id": (
        f"SELECT has_column_privilege('{READER_ROLE}', 'information.app_users', 'id', 'SELECT')"
    ),
    "reads_email": (
        f"SELECT has_column_privilege('{READER_ROLE}', 'information.app_users', 'email', 'SELECT')"
    ),
}


async def _seed(url: str, statements: list[str]) -> None:
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            for statement in statements:
                await conn.execute(text(statement))
    finally:
        await engine.dispose()


async def _read(url: str) -> dict:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            return {name: (await conn.execute(text(sql))).scalar() for name, sql in CHECKS.items()}
    finally:
        await engine.dispose()


def _ship(source: str, tmp_path: Path) -> tuple[FakeClient, dict]:
    client = FakeClient(FakeBucket(BUCKET))
    summary = backup.run_backup(
        database=_libpq(source),
        bucket=BUCKET,
        prefix="rehearsal",
        client=client,
        workdir=tmp_path / "backup",
        host="rehearsal",
    )
    return client, summary


async def test_a_dump_survives_the_round_trip_whole(databases, tmp_path: Path) -> None:
    source, target = databases
    await _seed(source, SEED)

    client, summary = _ship(source, tmp_path)
    assert summary["outcome"] == "uploaded"
    assert summary["alembic_head"] == "rehearsal01"

    restore.assert_empty(_libpq(target), run_as=None, runner=subprocess.run)
    key = restore.latest_key(client, BUCKET, "rehearsal")
    path = restore.fetch(client, BUCKET, key, tmp_path / "fetched", runner=subprocess.run)
    restore.restore_into(path, _libpq(target), run_as=None, runner=subprocess.run)

    before, after = await _read(source), await _read(target)
    assert after == before
    assert after["items"] == 25
    assert after["emails"] == "a@example.com,b@example.com"
    assert after["head"] == "rehearsal01"
    assert after["reads_items"] is True
    assert after["reads_id"] is True
    assert after["reads_email"] is False


async def test_a_restored_database_is_no_longer_a_target(databases, tmp_path: Path) -> None:
    """The emptiness probe, against a real catalogue: a fresh database passes
    (its empty ``public`` schema is not content), a seeded one does not."""
    source, target = databases
    restore.assert_empty(_libpq(target), run_as=None, runner=subprocess.run)
    await _seed(source, SEED[:3])
    with pytest.raises(restore.RestoreError, match="not empty"):
        restore.assert_empty(_libpq(source), run_as=None, runner=subprocess.run)


async def test_a_truncated_dump_is_refused_though_it_still_lists(databases, tmp_path: Path) -> None:
    """The premise, on a real archive: ``pg_restore --list`` passes a dump cut
    short, because the table of contents precedes the data. ``verify_dump``
    must not: it reads every block through."""
    source, _ = databases
    await _seed(
        source,
        [
            *SEED[:4],
            "INSERT INTO information.info_items (name) "
            "SELECT md5(g::text) FROM generate_series(1, 20000) g",
        ],
    )
    dump = backup.take_dump(
        _libpq(source), tmp_path / "backup", runner=subprocess.run, now=lambda: datetime.now(UTC)
    )
    cut = tmp_path / "cut.dump"
    cut.write_bytes(dump.path.read_bytes()[: dump.size_bytes * 9 // 10])

    listed = subprocess.run(["pg_restore", "--list", str(cut)], capture_output=True, check=False)
    assert listed.returncode == 0, "premise: a truncated archive still lists"
    with pytest.raises(backup.BackupError, match="end of file"):
        backup.verify_dump(cut, runner=subprocess.run)


async def test_a_restore_that_fails_partway_changes_nothing(databases, tmp_path: Path) -> None:
    """One transaction: a restore that fails partway leaves the target exactly
    as it was. The emptiness probe stops this case first; this is the line
    behind it.

    The conflict must come *late*: a target holding anything in ``information``
    fails at the dump's first statement, ``CREATE SCHEMA``, and the test would
    pass with the flag removed. So both hold ``public.zz_conflict``, which
    pg_dump orders after every ``information`` table: the restore creates the
    schema and its tables, then fails, and only ``--single-transaction`` takes
    them back out."""
    source, target = databases
    conflict = "CREATE TABLE public.zz_conflict (id int)"
    await _seed(source, [*SEED[:5], conflict])
    await _seed(target, [conflict, "INSERT INTO public.zz_conflict VALUES (1), (2), (3)"])

    client, _ = _ship(source, tmp_path)
    path = restore.fetch(
        client,
        BUCKET,
        restore.latest_key(client, BUCKET, "rehearsal"),
        tmp_path / "fetched",
        runner=subprocess.run,
    )
    with pytest.raises(restore.RestoreError, match="zz_conflict"):
        restore.restore_into(path, _libpq(target), run_as=None, runner=subprocess.run)

    engine = create_async_engine(target)
    async with engine.connect() as conn:
        count = await conn.execute(text("SELECT count(*) FROM public.zz_conflict"))
        assert count.scalar() == 3
        leftover = await conn.execute(text("SELECT to_regnamespace('information')"))
        assert leftover.scalar() is None, "the restore's first CREATEs outlived its failure"
    await engine.dispose()
