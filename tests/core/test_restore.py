"""``src.core.restore``: bringing a shipped dump back (archiver#233).

Ported from CannObserv/watcher's ``tests/ops/test_restore.py`` (watcher#296 D8),
plus Archiver's target guard: ``--into`` refuses the production database unless
the operator says so, and refuses any database that already holds something.
"""

import hashlib
import logging
import os
import re
import stat
import subprocess
from datetime import UTC, datetime, timedelta

import pytest
from google.api_core.exceptions import Forbidden

from src.core import restore
from src.core.backup import BUCKET_ENV, KEY_TIME_FORMAT, PREFIX_ENV
from src.core.restore import RestoreError
from tests.core.gcs_fakes import FakeBucket, FakeClient
from tests.core.test_backup import DUMP_BYTES, FakePg

BUCKET = "co-gcs-archiver-backup"
SRC = "co-registrar"


def _ship(
    bucket: FakeBucket,
    key: str,
    data: bytes = DUMP_BYTES,
    *,
    created: datetime | None = None,
    **meta,
) -> None:
    """Put an object where the backup would, with the digest it records.

    Created a minute after the time its name claims, as an honest upload is —
    unless ``created`` says otherwise (a forged, future-dated name).
    """
    bucket.objects[key] = data
    bucket.metadata[key] = {"sha256": hashlib.sha256(data).hexdigest(), **meta}
    if created is None:
        match = re.search(r"(\d{8}T\d{6}Z)\.dump$", key)
        stamp = datetime.strptime(match.group(1), KEY_TIME_FORMAT) if match else datetime.now()
        created = stamp.replace(tzinfo=UTC) + timedelta(minutes=1)
    bucket.created[key] = created


class RefreshError(Exception):
    """Stands in for ``google.auth.exceptions.RefreshError`` (a revoked key): like
    it, neither a RestoreError nor a GoogleAPICallError."""


def _raiser(error: Exception):
    """A stand-in for any callable, raising ``error`` however it is called."""

    def raise_it(*_args, **_kwargs):
        raise error

    return raise_it


@pytest.fixture
def bucket() -> FakeBucket:
    return FakeBucket(BUCKET)


@pytest.fixture
def client(bucket) -> FakeClient:
    return FakeClient(bucket)


class TestFindingASnapshot:
    def test_list_reads_names_and_metadata_in_time_order(self, client, bucket) -> None:
        _ship(bucket, f"{SRC}/20261014T031702Z.dump", alembic_head="b")
        _ship(bucket, f"{SRC}/20261013T031702Z.dump", alembic_head="a")
        _ship(bucket, "other/20261012T000000Z.dump")
        listed = restore.list_snapshots(client, BUCKET, SRC)
        assert [snapshot.name for snapshot in listed] == [
            f"{SRC}/20261013T031702Z.dump",
            f"{SRC}/20261014T031702Z.dump",
        ]
        assert listed[1].metadata["alembic_head"] == "b"

    def test_latest_is_the_newest_name(self, client, bucket) -> None:
        _ship(bucket, f"{SRC}/20261013T031702Z.dump")
        _ship(bucket, f"{SRC}/20261014T031702Z.dump")
        assert restore.latest_key(client, BUCKET, SRC) == f"{SRC}/20261014T031702Z.dump"

    def test_no_snapshot_is_an_error(self, client) -> None:
        with pytest.raises(RestoreError, match="no dumps"):
            restore.latest_key(client, BUCKET, SRC)

    def test_latest_passes_over_a_name_later_than_its_upload(self, client, bucket, caplog) -> None:
        """A name is the writer's claim; the creation time is the bucket's. A
        compromised writer planting ``2099…`` would otherwise own ``--latest``
        for the 30 days the lifecycle rule takes to remove it."""
        _ship(bucket, f"{SRC}/20261013T031702Z.dump")
        _ship(
            bucket,
            f"{SRC}/20990101T000000Z.dump",
            created=datetime(2026, 10, 13, 12, 0, tzinfo=UTC),
        )
        with caplog.at_level(logging.WARNING, logger="src.core.restore"):
            assert restore.latest_key(client, BUCKET, SRC) == f"{SRC}/20261013T031702Z.dump"
        assert any("20990101T000000Z" in r.getMessage() for r in caplog.records)

    def test_a_name_within_clock_skew_of_its_upload_is_still_a_candidate(
        self, client, bucket
    ) -> None:
        _ship(
            bucket,
            f"{SRC}/20261013T031702Z.dump",
            created=datetime(2026, 10, 13, 3, 16, 30, tzinfo=UTC),
        )
        assert restore.latest_key(client, BUCKET, SRC) == f"{SRC}/20261013T031702Z.dump"

    def test_only_suspect_names_is_no_dump_at_all(self, client, bucket) -> None:
        _ship(
            bucket,
            f"{SRC}/20990101T000000Z.dump",
            created=datetime(2026, 10, 13, 12, 0, tzinfo=UTC),
        )
        with pytest.raises(RestoreError, match="no dumps"):
            restore.latest_key(client, BUCKET, SRC)


class TestFetch:
    def test_downloads_and_verifies(self, client, bucket, tmp_path) -> None:
        _ship(bucket, f"{SRC}/x.dump")
        path = restore.fetch(client, BUCKET, f"{SRC}/x.dump", tmp_path / "d", runner=FakePg())
        assert path.read_bytes() == DUMP_BYTES

    def test_a_download_that_does_not_match_its_recorded_digest_is_refused(
        self, client, bucket, tmp_path
    ) -> None:
        _ship(bucket, f"{SRC}/x.dump")
        bucket.objects[f"{SRC}/x.dump"] = DUMP_BYTES + b"tampered"
        with pytest.raises(RestoreError, match="sha256"):
            restore.fetch(client, BUCKET, f"{SRC}/x.dump", tmp_path / "d", runner=FakePg())
        assert list((tmp_path / "d").iterdir()) == []

    def test_a_dump_without_a_recorded_digest_is_refused(self, client, bucket, tmp_path) -> None:
        bucket.objects[f"{SRC}/x.dump"] = DUMP_BYTES
        with pytest.raises(RestoreError, match="sha256"):
            restore.fetch(client, BUCKET, f"{SRC}/x.dump", tmp_path / "d", runner=FakePg())

    def test_a_missing_object_is_an_error(self, client, tmp_path) -> None:
        with pytest.raises(RestoreError, match="not found"):
            restore.fetch(client, BUCKET, f"{SRC}/nope.dump", tmp_path / "d", runner=FakePg())

    def test_an_archive_pg_restore_cannot_read_is_refused(self, client, bucket, tmp_path) -> None:
        _ship(bucket, f"{SRC}/x.dump")
        with pytest.raises(RestoreError, match="pg_restore"):
            restore.fetch(
                client, BUCKET, f"{SRC}/x.dump", tmp_path / "d", runner=FakePg(fail="pg_restore")
            )


class TestFetchIsPrivate:
    """A fetched dump is the whole production database, personal data included
    (``app_users.email``, ``api_keys.key_hash``), fetched as root.

    sudo's umask is 0022, so a plain ``mkdir`` and the SDK's plain ``open``
    would leave a 0644 dump in a 0755 directory, and a directory someone else
    made first could hold a symlink for root to write through.
    """

    @pytest.fixture(autouse=True)
    def _sudo_umask(self):
        previous = os.umask(0o022)
        yield
        os.umask(previous)

    def test_the_directory_and_the_dump_are_private(self, client, bucket, tmp_path) -> None:
        _ship(bucket, f"{SRC}/x.dump")
        dest = tmp_path / "fetched"
        path = restore.fetch(client, BUCKET, f"{SRC}/x.dump", dest, runner=FakePg())
        assert stat.S_IMODE(dest.stat().st_mode) == 0o700
        assert stat.S_IMODE(path.stat().st_mode) == 0o600

    def test_a_directory_others_can_enter_is_refused(self, client, bucket, tmp_path) -> None:
        _ship(bucket, f"{SRC}/x.dump")
        dest = tmp_path / "shared"
        dest.mkdir(mode=0o755)
        with pytest.raises(RestoreError, match="private"):
            restore.fetch(client, BUCKET, f"{SRC}/x.dump", dest, runner=FakePg())
        assert list(dest.iterdir()) == []

    def test_a_directory_someone_else_owns_is_refused(
        self, client, bucket, tmp_path, monkeypatch
    ) -> None:
        _ship(bucket, f"{SRC}/x.dump")
        dest = tmp_path / "theirs"
        dest.mkdir(mode=0o700)
        someone_else = os.geteuid() + 1
        monkeypatch.setattr(restore.os, "geteuid", lambda: someone_else)
        with pytest.raises(RestoreError, match="owned"):
            restore.fetch(client, BUCKET, f"{SRC}/x.dump", dest, runner=FakePg())

    def test_a_planted_link_is_not_written_through(self, client, bucket, tmp_path) -> None:
        _ship(bucket, f"{SRC}/x.dump")
        dest = tmp_path / "fetched"
        dest.mkdir(mode=0o700)
        victim = tmp_path / "victim"
        victim.write_bytes(b"precious")
        (dest / "x.dump").symlink_to(victim)
        with pytest.raises(RestoreError, match="exists"):
            restore.fetch(client, BUCKET, f"{SRC}/x.dump", dest, runner=FakePg())
        assert victim.read_bytes() == b"precious"


class TestAsUser:
    def test_drops_privileges_with_setpriv(self) -> None:
        """``setpriv``: a plain exec with no PAM session, the same from a login
        shell, ``sudo`` or a sandbox."""
        assert restore.as_user(["pg_restore", "archiver"], "postgres") == [
            "setpriv",
            "--reuid=postgres",
            "--regid=postgres",
            "--init-groups",
            "--reset-env",
            "--",
            "pg_restore",
            "archiver",
        ]

    def test_the_dropped_to_user_inherits_none_of_the_callers_environment(self) -> None:
        argv = restore.as_user(["pg_restore"], "postgres")
        assert "--reset-env" in argv[: argv.index("--")]

    def test_without_a_user_is_the_command_itself(self) -> None:
        assert restore.as_user(["pg_restore", "x"], None) == ["pg_restore", "x"]


class TestTheTarget:
    """``--into`` is the one step that writes a database. The guard reuses
    ``db_safety``'s boundary, the name's ``_test``/``_dev`` suffix."""

    @pytest.mark.parametrize(
        "database",
        [
            "archiver_test",
            "archiver_restore_dev",
            "postgresql://u:p@localhost:5432/archiver_rh1_test",
            "postgresql+asyncpg://u:p@localhost/x_dev?sslmode=disable",
        ],
    )
    def test_a_disposable_database_is_allowed(self, database) -> None:
        assert restore.production_refusal(database, allow_production=False) is None

    @pytest.mark.parametrize(
        "database",
        ["archiver", "archiver_testing", "test_archiver", "postgresql://u:p@localhost/archiver"],
    )
    def test_a_production_name_is_refused(self, database) -> None:
        refusal = restore.production_refusal(database, allow_production=False)
        assert refusal and "--allow-production" in refusal

    def test_a_production_name_is_allowed_when_the_operator_says_so(self) -> None:
        assert restore.production_refusal("archiver", allow_production=True) is None

    @pytest.mark.parametrize(
        "database", ["host=localhost dbname=archiver_test", "", "postgresql:///"]
    )
    def test_a_target_whose_name_cannot_be_read_is_refused_even_so(self, database) -> None:
        """Fail closed: a name the guard cannot read is not one it can pass."""
        refusal = restore.production_refusal(database, allow_production=True)
        assert refusal and "name" in refusal

    def test_an_empty_database_passes(self) -> None:
        restore.assert_empty("archiver_restore_test", run_as=None, runner=FakePg(objects=0))

    def test_a_database_that_holds_anything_is_refused(self) -> None:
        """Never ``--clean``: a restore adds to nothing, so a target holding a
        schema or a table is refused before the dump is fetched."""
        with pytest.raises(RestoreError, match="not empty"):
            restore.assert_empty("archiver_test", run_as=None, runner=FakePg(objects=3))

    def test_a_database_that_cannot_be_reached_is_refused(self) -> None:
        with pytest.raises(RestoreError, match="psql"):
            restore.assert_empty("archiver_test", run_as=None, runner=FakePg(fail="psql"))

    def test_the_probe_runs_as_the_restoring_user(self) -> None:
        pg = FakePg()
        restore.assert_empty("archiver", run_as="postgres", runner=pg)
        (call,) = pg.calls
        assert call[:2] == ["setpriv", "--reuid=postgres"]
        assert "--dbname=archiver" in call


class TestRestoreInto:
    def test_one_transaction_through_stdin_as_postgres(self, tmp_path) -> None:
        """All or nothing, so a failed restore leaves an empty database rather
        than half of one. Through stdin, so ``postgres`` never needs to read a
        file root wrote. Never ``--clean``."""
        dump = tmp_path / "x.dump"
        dump.write_bytes(DUMP_BYTES)
        seen: dict = {}

        def runner(argv, **kwargs):
            seen["argv"] = argv
            seen["stdin"] = kwargs["stdin"].read()
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

        restore.restore_into(dump, "archiver", run_as="postgres", runner=runner)
        assert seen["argv"][:6] == [
            "setpriv",
            "--reuid=postgres",
            "--regid=postgres",
            "--init-groups",
            "--reset-env",
            "--",
        ]
        assert {"--single-transaction", "--exit-on-error", "--dbname=archiver"} <= set(seen["argv"])
        assert not [a for a in seen["argv"] if a.startswith(("--clean", "-c"))]
        assert seen["stdin"] == DUMP_BYTES

    def test_a_failed_restore_is_an_error(self, tmp_path) -> None:
        dump = tmp_path / "x.dump"
        dump.write_bytes(DUMP_BYTES)
        with pytest.raises(RestoreError, match="pg_restore"):
            restore.restore_into(dump, "archiver", run_as=None, runner=FakePg(fail="pg_restore"))


class TestMain:
    @pytest.fixture
    def pg(self, monkeypatch, client) -> FakePg:
        pg = FakePg()
        monkeypatch.setattr(restore.storage, "Client", lambda: client)
        monkeypatch.setattr(restore.subprocess, "run", pg)
        monkeypatch.setenv(BUCKET_ENV, BUCKET)
        # A restoring host's own prefix: never the one it restores from.
        monkeypatch.setenv(PREFIX_ENV, "replacement")
        return pg

    def test_latest_needs_the_source_host_named(self, pg, bucket, tmp_path, capsys) -> None:
        """A restore runs on another host — an incident's replacement — so a
        default prefix is the restoring host's, the one prefix never wanted."""
        _ship(bucket, f"{SRC}/20261013T031702Z.dump")
        assert restore.main(["--latest", "--download-only", str(tmp_path / "d")]) == 2
        assert "--prefix" in capsys.readouterr().err

    def test_latest_takes_the_named_hosts_newest_not_this_hosts(self, pg, bucket, tmp_path) -> None:
        _ship(bucket, f"{SRC}/20261013T031702Z.dump")
        _ship(bucket, "replacement/20261014T031702Z.dump", DUMP_BYTES + b"the new host's own")
        dest = tmp_path / "d"
        assert restore.main(["--latest", "--prefix", SRC, "--download-only", str(dest)]) == 0
        assert [p.name for p in dest.iterdir()] == ["20261013T031702Z.dump"]

    def test_list_without_a_prefix_shows_every_host(self, pg, bucket, capsys) -> None:
        _ship(bucket, f"{SRC}/20261013T031702Z.dump")
        _ship(bucket, "replacement/20261014T031702Z.dump")
        assert restore.main(["--list"]) == 0
        out = capsys.readouterr().out
        assert f"{SRC}/20261013T031702Z.dump" in out
        assert "replacement/20261014T031702Z.dump" in out

    def test_list_flags_a_name_later_than_its_upload(self, pg, bucket, capsys) -> None:
        _ship(bucket, f"{SRC}/20261013T031702Z.dump")
        _ship(
            bucket,
            f"{SRC}/20990101T000000Z.dump",
            created=datetime(2026, 10, 13, 12, 0, tzinfo=UTC),
        )
        assert restore.main(["--list", "--prefix", SRC]) == 0
        lines = capsys.readouterr().out.splitlines()
        (forged,) = [line for line in lines if "20990101T000000Z" in line]
        (honest,) = [line for line in lines if "20261013T031702Z" in line]
        assert "SUSPECT" in forged
        assert "SUSPECT" not in honest

    def test_no_bucket_is_a_usage_error(self, pg, monkeypatch, capsys) -> None:
        monkeypatch.delenv(BUCKET_ENV)
        assert restore.main(["--list"]) == 2
        assert BUCKET_ENV in capsys.readouterr().err

    def test_a_dump_with_nowhere_to_go_is_a_usage_error(self, pg, bucket, capsys) -> None:
        _ship(bucket, f"{SRC}/20261013T031702Z.dump")
        assert restore.main(["--object", f"{SRC}/20261013T031702Z.dump"]) == 2
        assert "say where" in capsys.readouterr().err

    def test_object_fetches_exactly_that_dump(self, pg, bucket, tmp_path) -> None:
        _ship(bucket, f"{SRC}/20261012T031702Z.dump")
        _ship(bucket, f"{SRC}/20261013T031702Z.dump")
        dest = tmp_path / "d"
        key = f"{SRC}/20261012T031702Z.dump"
        assert restore.main(["--object", key, "--download-only", str(dest)]) == 0
        assert [p.name for p in dest.iterdir()] == ["20261012T031702Z.dump"]

    def test_a_restore_that_lands_names_the_next_step(self, pg, bucket, capsys) -> None:
        _ship(bucket, f"{SRC}/20261013T031702Z.dump")
        code = restore.main(["--latest", "--prefix", SRC, "--into", "archiver_restore_test"])
        assert code == 0
        out = capsys.readouterr().out
        # Named, not half-quoted: the grants run in a superuser session under
        # SET ROLE archiver, which a bare command line would leave out.
        assert "read role's grants" in out
        assert "scripts/setup-backup-role.sql" in out
        assert "docs/BACKUP.md § Restore" in out

    def test_into_production_is_refused_before_anything_is_fetched(
        self, pg, bucket, client, monkeypatch, capsys
    ) -> None:
        _ship(bucket, f"{SRC}/20261013T031702Z.dump")
        built: list[int] = []
        monkeypatch.setattr(restore.storage, "Client", lambda: built.append(1) or client)
        assert restore.main(["--latest", "--prefix", SRC, "--into", "archiver"]) == 2
        assert "--allow-production" in capsys.readouterr().err
        assert built == []
        assert pg.calls == []

    def test_into_production_with_the_override_restores(self, pg, bucket) -> None:
        _ship(bucket, f"{SRC}/20261013T031702Z.dump")
        argv = ["--latest", "--prefix", SRC, "--into", "archiver", "--allow-production"]
        assert restore.main([*argv, "--run-as", "postgres"]) == 0
        restored = [c for c in pg.calls if "--single-transaction" in c]
        assert len(restored) == 1 and restored[0][0] == "setpriv"

    def test_a_password_on_the_command_line_is_refused(self, pg, capsys) -> None:
        """psql and pg_restore would carry it in a world-readable argv."""
        into = "postgresql://u:s3cret@localhost/archiver_restore_test"
        assert restore.main(["--latest", "--prefix", SRC, "--into", into]) == 2
        err = capsys.readouterr().err
        assert "password" in err and "s3cret" not in err
        assert pg.calls == []

    def test_the_override_is_only_for_into(self, pg, tmp_path, capsys) -> None:
        argv = ["--latest", "--prefix", SRC, "--download-only", str(tmp_path / "d")]
        assert restore.main([*argv, "--allow-production"]) == 2
        assert "--allow-production" in capsys.readouterr().err

    def test_a_populated_target_is_refused_before_anything_is_fetched(
        self, pg, bucket, monkeypatch, capsys
    ) -> None:
        _ship(bucket, f"{SRC}/20261013T031702Z.dump")
        monkeypatch.setattr(restore.subprocess, "run", populated := FakePg(objects=17))
        assert restore.main(["--latest", "--prefix", SRC, "--into", "archiver_test"]) == 1
        assert "not empty" in capsys.readouterr().err
        assert [c[0] for c in populated.calls] == ["psql"]

    @pytest.mark.parametrize("where", ["client", "listing", "restore"])
    def test_any_failure_is_one_line_and_exit_1(
        self, pg, bucket, monkeypatch, capsys, where
    ) -> None:
        """At the worst moment the operator gets a sentence, not a stack trace."""
        _ship(bucket, f"{SRC}/20261013T031702Z.dump")
        if where == "client":
            monkeypatch.setattr(restore.storage, "Client", _raiser(RefreshError("revoked")))
        elif where == "listing":
            monkeypatch.setattr(FakeClient, "list_blobs", _raiser(Forbidden("no list")))
        else:

            def runner(argv, **kwargs):
                if "stdin" in kwargs:
                    raise subprocess.TimeoutExpired(argv, 1800)
                return pg(argv, **kwargs)

            monkeypatch.setattr(restore.subprocess, "run", runner)
        code = restore.main(["--latest", "--prefix", SRC, "--into", "archiver_restore_test"])
        assert code == 1
        err = capsys.readouterr().err
        assert err.startswith("restore failed:")
        assert "Traceback" not in err

    def test_an_empty_listing_says_so(self, pg, bucket, capsys) -> None:
        _ship(bucket, f"{SRC}/20261013T031702Z.dump")
        assert restore.main(["--list", "--prefix", "replacement"]) == 0
        assert f"no dumps under gs://{BUCKET}/replacement/" in capsys.readouterr().err
