"""``src.core.backup``: the nightly dump to GCS (archiver#233).

Ported from CannObserv/watcher's ``tests/ops/test_backup.py`` (watcher#296 D8,
#297), on broker#4's pattern. Every decision runs against fakes — which key,
which precondition, what the job refuses to ship, when it checks in. What a fake
cannot answer (whether a real ``pg_dump`` round-trips the ``information``
schema) is ``test_backup_restore_rehearsal.py``'s, against a real server.

Never the network, and never the real monitor or key: Status is stubbed with
respx, and a stray ``ok`` would reset the dead-man clock (status#32).
"""

import json
import logging
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx

from src.core import backup
from src.core.backup import BackupError
from src.core.status_checkin import CREDENTIAL_NAME, DEFAULT_STATUS_URL, STATUS_URL_ENV
from tests.core.gcs_fakes import FakeBucket, FakeClient

BUCKET = "co-gcs-archiver-backup"
NOW = datetime(2026, 10, 14, 3, 17, 2, 512000, tzinfo=UTC)
DUMP_BYTES = b"PGDMP\x01\x0f\x00" + b"x" * 64
#: Not the real co-archiver-backup monitor: a stray ``ok`` masks real silence.
MONITOR_ID = "01M4KMDDN3XWJR0GCECTAYMVT0"
CHECKIN_URL = f"{DEFAULT_STATUS_URL}/api/v1/monitors/{MONITOR_ID}/checkin"

#: ``pg_restore --list`` on a real custom-format dump of archiver, header
#: verbatim (the entries trimmed to the ones the check reads).
TOC = """\
;
; Archive created at 2026-10-14 03:17:02 UTC
;     dbname: archiver
;     TOC Entries: 214
;     Compression: gzip
;     Dump Version: 1.15-0
;     Format: CUSTOM
;     Integer: 4 bytes
;     Offset: 8 bytes
;     Dumped from database version: 16.15 (Ubuntu 16.15-0ubuntu0.24.04.1)
;     Dumped by pg_dump version: 16.15 (Ubuntu 16.15-0ubuntu0.24.04.1)
;
;
; Selected TOC Entries:
;
6; 2615 16390 SCHEMA - information archiver
3601; 0 16391 TABLE DATA information alembic_version archiver
3610; 0 16420 TABLE DATA information info_items archiver
3612; 0 16450 TABLE DATA information app_users archiver
"""


class DefaultCredentialsError(Exception):
    """Stands in for ``google.auth.exceptions.DefaultCredentialsError``: like it,
    neither a BackupError nor a GoogleAPICallError."""


class FakePg:
    """Answers pg_dump, psql and pg_restore the way the real ones do — behind
    ``setpriv`` too, as the restore runs them."""

    def __init__(
        self,
        *,
        toc: str = TOC,
        head: str = "b7e3c1a9d042",
        fail: str = "",
        truncated: bool = False,
        objects: int = 0,
    ) -> None:
        self.toc = toc
        self.head = head
        self.fail = fail
        # A custom-format archive cut short still lists: its table of contents
        # precedes the data. Only reading the data through finds the cut.
        self.truncated = truncated
        #: What the restore's emptiness probe counts in its target.
        self.objects = objects
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], **kwargs) -> subprocess.CompletedProcess:
        self.calls.append(argv)
        program = argv[argv.index("--") + 1] if argv[0] == "setpriv" else argv[0]
        if program == self.fail:
            return subprocess.CompletedProcess(argv, 1, stdout="", stderr=f"{program}: boom\n")
        if program == "pg_dump":
            kwargs["stdout"].write(DUMP_BYTES)
            return subprocess.CompletedProcess(argv, 0, stdout=None, stderr=b"")
        if program == "psql":
            query = next(a for a in argv if a.startswith("--command="))
            answer = self.head if "alembic_version" in query else str(self.objects)
            return subprocess.CompletedProcess(argv, 0, stdout=f"{answer}\n", stderr="")
        if program == "pg_restore" and "--file=/dev/null" in argv:
            if self.truncated:
                error = "pg_restore: error: could not read from input file: end of file\n"
                return subprocess.CompletedProcess(argv, 1, stdout="", stderr=error)
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        if program == "pg_restore" and "--list" in argv:
            return subprocess.CompletedProcess(argv, 0, stdout=self.toc, stderr="")
        if program == "pg_restore":
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        raise AssertionError(f"unexpected program {program}")


@pytest.fixture
def bucket() -> FakeBucket:
    return FakeBucket(BUCKET)


@pytest.fixture
def client(bucket) -> FakeClient:
    return FakeClient(bucket)


def _run(client, tmp_path: Path, **overrides) -> dict:
    kwargs = dict(
        database="archiver",
        bucket=BUCKET,
        prefix="co-registrar",
        client=client,
        workdir=tmp_path,
        runner=FakePg(),
        host="co-registrar",
        now=lambda: NOW,
    )
    kwargs.update(overrides)
    return backup.run_backup(**kwargs)


def _credentials(tmp_path: Path, key: str | None = "sk_backup") -> Path:
    """A ``$CREDENTIALS_DIRECTORY`` as the unit hands it over."""
    directory = tmp_path / "credentials"
    directory.mkdir(exist_ok=True)
    if key is not None:
        (directory / CREDENTIAL_NAME).write_text(f"{key}\n")
    return directory


# --- what a dump is ---


class TestPure:
    def test_parse_toc(self) -> None:
        toc = backup.parse_toc(TOC)
        assert toc.server_version == "16.15 (Ubuntu 16.15-0ubuntu0.24.04.1)"
        assert toc.pg_dump_version == "16.15 (Ubuntu 16.15-0ubuntu0.24.04.1)"
        assert toc.entries == 214
        assert {"information.alembic_version", "information.info_items"} <= toc.tables_with_data

    def test_object_key_is_the_dump_time(self) -> None:
        """A listing reads as a timeline and the newest name is the newest data."""
        assert backup.object_key("co-registrar", NOW) == "co-registrar/20261014T031702Z.dump"

    def test_the_required_tables_are_archivers(self) -> None:
        assert backup.REQUIRED_TABLES == ("information.alembic_version", "information.info_items")


# --- what the job refuses ---


class TestVerify:
    def test_a_dump_pg_restore_cannot_read_is_refused(self, tmp_path) -> None:
        path = tmp_path / "x.dump"
        path.write_bytes(b"not a dump")
        with pytest.raises(BackupError, match="pg_restore"):
            backup.verify_dump(path, runner=FakePg(fail="pg_restore"))

    def test_every_data_block_is_read_not_only_the_table_of_contents(self, tmp_path) -> None:
        path = tmp_path / "x.dump"
        path.write_bytes(DUMP_BYTES)
        pg = FakePg()
        backup.verify_dump(path, runner=pg)
        assert ["pg_restore", "--file=/dev/null", str(path)] in pg.calls

    def test_an_archive_that_lists_but_does_not_read_through_is_refused(self, tmp_path) -> None:
        """``--list`` reads the header and the table of contents, which custom
        format writes before the data, so a truncated archive lists cleanly
        (watcher measured: cut anywhere from 30 % to 99 %)."""
        path = tmp_path / "x.dump"
        path.write_bytes(DUMP_BYTES)
        with pytest.raises(BackupError, match="end of file"):
            backup.verify_dump(path, runner=FakePg(truncated=True))

    def test_a_dump_without_archivers_tables_is_refused(self, tmp_path) -> None:
        """A readable archive of the wrong database is not a backup of this one."""
        path = tmp_path / "x.dump"
        path.write_bytes(DUMP_BYTES)
        empty = TOC.split("6; 2615")[0]
        with pytest.raises(BackupError, match="info_items"):
            backup.verify_dump(path, runner=FakePg(toc=empty))

    def test_the_same_table_name_in_another_schema_is_not_archivers(self, tmp_path) -> None:
        path = tmp_path / "x.dump"
        path.write_bytes(DUMP_BYTES)
        public = TOC.replace("TABLE DATA information", "TABLE DATA public")
        with pytest.raises(BackupError, match="information.alembic_version"):
            backup.verify_dump(path, runner=FakePg(toc=public))


class TestTakeDump:
    def test_describes_the_dump(self, tmp_path) -> None:
        dump = backup.take_dump("archiver", tmp_path, runner=FakePg(), now=lambda: NOW)
        assert dump.path.read_bytes() == DUMP_BYTES
        assert dump.size_bytes == len(DUMP_BYTES)
        assert len(dump.sha256) == 64
        assert dump.dumped_at == NOW.replace(microsecond=0)
        assert dump.alembic_head == "b7e3c1a9d042"
        assert dump.toc.entries == 214

    def test_reads_the_head_from_the_information_schema(self, tmp_path) -> None:
        """alembic is scoped to ``information``; ``public`` is empty."""
        pg = FakePg()
        backup.take_dump("archiver", tmp_path, runner=pg, now=lambda: NOW)
        (psql,) = [call for call in pg.calls if call[0] == "psql"]
        assert "--command=SELECT version_num FROM information.alembic_version" in psql
        assert "--dbname=archiver" in psql

    def test_the_database_is_read_as_the_jobs_own_user(self, tmp_path) -> None:
        """No privilege is dropped because none is held: the unit's user is the
        role the database knows, by peer auth over the socket, so no command
        holds a credential."""
        pg = FakePg()
        backup.take_dump("archiver", tmp_path, runner=pg, now=lambda: NOW)
        assert {call[0] for call in pg.calls} == {"psql", "pg_dump", "pg_restore"}
        (dump_call,) = [call for call in pg.calls if call[0] == "pg_dump"]
        assert "--format=custom" in dump_call
        assert "--no-password" in dump_call
        assert "--dbname=archiver" in dump_call

    def test_a_dump_gives_up_on_a_lock_rather_than_queueing(self, tmp_path) -> None:
        """A dump behind a migration's ACCESS EXCLUSIVE would queue, and every
        reader after it: it fails instead, and the next night is the retry."""
        pg = FakePg()
        backup.take_dump("archiver", tmp_path, runner=pg, now=lambda: NOW)
        (dump_call,) = [call for call in pg.calls if call[0] == "pg_dump"]
        assert "--lock-wait-timeout=30s" in dump_call

    def test_a_failed_pg_dump_is_a_failure(self, tmp_path) -> None:
        with pytest.raises(BackupError, match="pg_dump"):
            backup.take_dump("archiver", tmp_path, runner=FakePg(fail="pg_dump"), now=lambda: NOW)

    def test_an_unreadable_head_is_a_failure(self, tmp_path) -> None:
        with pytest.raises(BackupError, match="alembic_version"):
            backup.take_dump("archiver", tmp_path, runner=FakePg(fail="psql"), now=lambda: NOW)


# --- the bucket ---


class TestUpload:
    def test_creates_the_object_with_its_metadata(self, client, bucket, tmp_path) -> None:
        summary = _run(client, tmp_path)
        key = "co-registrar/20261014T031702Z.dump"
        assert summary["outcome"] == "uploaded"
        assert summary["object"] == f"gs://{BUCKET}/{key}"
        assert bucket.objects[key] == DUMP_BYTES
        assert bucket.preconditions == [0]
        meta = bucket.metadata[key]
        assert meta["sha256"] == summary["sha256"]
        assert meta["alembic_head"] == "b7e3c1a9d042"
        assert meta["source_host"] == "co-registrar"
        assert meta["server_version"].startswith("16.15")
        assert meta["dumped_at"] == "2026-10-14T03:17:02Z"

    def test_the_same_dump_twice_is_unchanged(self, client, tmp_path) -> None:
        """A 412 on the create is a success when the object holds these bytes."""
        _run(client, tmp_path)
        assert _run(client, tmp_path)["outcome"] == "unchanged"

    def test_a_different_dump_under_the_same_name_is_a_failure(
        self, client, bucket, tmp_path
    ) -> None:
        """Two pg_dumps are never the same bytes, so a name collision (two runs
        in one second) must not read as ``unchanged``."""
        _run(client, tmp_path)
        bucket.metadata["co-registrar/20261014T031702Z.dump"]["sha256"] = "0" * 64
        with pytest.raises(BackupError, match="already exists"):
            _run(client, tmp_path)

    def test_a_412_on_an_object_that_cannot_be_read_back_is_a_failure(
        self, client, tmp_path, monkeypatch
    ) -> None:
        _run(client, tmp_path)
        monkeypatch.setattr(FakeBucket, "get_blob", lambda self, name, timeout=None: None)
        with pytest.raises(BackupError, match="could not be read back"):
            _run(client, tmp_path)

    def test_a_missing_bucket_fails_before_anything_is_dumped(self, tmp_path) -> None:
        """The bucket is the cheap thing to check, and a misspelled one should
        not cost a pg_dump of production."""
        pg = FakePg()
        with pytest.raises(BackupError, match="not found"):
            _run(FakeClient(FakeBucket(BUCKET), missing=True), tmp_path, runner=pg)
        assert pg.calls == []


# --- the check-in ---


class TestCheckin:
    """A failed check-in never changes the backup's result: the guard logs and
    returns, and the monitor's silence is the alarm."""

    @pytest.fixture
    def environ(self, tmp_path) -> dict[str, str]:
        return {
            backup.MONITOR_ID_ENV: MONITOR_ID,
            backup.CREDENTIALS_DIRECTORY_ENV: str(_credentials(tmp_path)),
        }

    @respx.mock
    def test_ok_posts_the_summary_as_strings(self, environ) -> None:
        route = respx.post(CHECKIN_URL).mock(return_value=httpx.Response(202))
        assert backup.checkin("ok", {"size_bytes": 72, "alembic_head": None}, environ=environ)
        (call,) = route.calls
        assert call.request.headers["X-API-Key"] == "sk_backup"
        body = json.loads(call.request.content)
        assert body == {"status": "ok", "variables": {"size_bytes": "72", "alembic_head": ""}}

    @respx.mock
    def test_an_alert_names_its_fault(self, environ) -> None:
        """status#28: a run of alerts is one fault; a change of fault reports."""
        route = respx.post(CHECKIN_URL).mock(return_value=httpx.Response(202))
        backup.checkin("alert", {"error": "boom"}, fault="failed", environ=environ)
        body = json.loads(route.calls[0].request.content)
        assert body["metadata"] == {"fault": "failed"}

    @respx.mock
    def test_the_status_url_is_configuration(self, environ) -> None:
        route = respx.post(f"http://status.test:9001/api/v1/monitors/{MONITOR_ID}/checkin").mock(
            return_value=httpx.Response(202)
        )
        assert backup.checkin(
            "ok", {}, environ=environ | {STATUS_URL_ENV: "http://status.test:9001"}
        )
        assert route.called

    @respx.mock
    def test_no_monitor_sends_nothing_and_says_a_stop_goes_unnoticed(
        self, tmp_path, caplog
    ) -> None:
        """Until co-status creates the monitor, the unit runs without an id."""
        route = respx.post(url__regex=r".*").mock(return_value=httpx.Response(202))
        environ = {backup.CREDENTIALS_DIRECTORY_ENV: str(_credentials(tmp_path))}
        with caplog.at_level(logging.WARNING, logger="src.core.backup"):
            assert not backup.checkin("ok", {}, environ=environ)
        assert not route.called
        assert "will not be noticed" in caplog.text

    @respx.mock
    def test_a_monitor_id_that_is_not_a_ulid_sends_nothing(self, environ, caplog) -> None:
        route = respx.post(url__regex=r".*").mock(return_value=httpx.Response(202))
        assert not backup.checkin("ok", {}, environ=environ | {backup.MONITOR_ID_ENV: "../x"})
        assert not route.called

    @respx.mock
    @pytest.mark.parametrize("key", [None, ""], ids=["absent", "the-empty-fallback"])
    def test_no_key_sends_nothing(self, tmp_path, key, caplog) -> None:
        route = respx.post(url__regex=r".*").mock(return_value=httpx.Response(202))
        environ = {
            backup.MONITOR_ID_ENV: MONITOR_ID,
            backup.CREDENTIALS_DIRECTORY_ENV: str(_credentials(tmp_path, key)),
        }
        with caplog.at_level(logging.ERROR, logger="src.core.backup"):
            assert not backup.checkin("ok", {}, environ=environ)
        assert not route.called
        assert CREDENTIAL_NAME in caplog.text

    @respx.mock
    @pytest.mark.parametrize(
        "answer",
        [httpx.Response(401, json={"detail": "bad key"}), httpx.ConnectError("refused")],
        ids=["refused", "unreachable"],
    )
    def test_a_check_in_status_does_not_take_is_logged_never_raised(
        self, environ, answer, caplog
    ) -> None:
        respx.post(CHECKIN_URL).mock(side_effect=[answer])
        with caplog.at_level(logging.ERROR, logger="src.core.backup"):
            assert not backup.checkin("ok", {}, environ=environ)
        assert "Check-in ok failed" in caplog.text
        assert "sk_backup" not in caplog.text

    def test_a_status_url_httpx_cannot_parse_is_logged_never_raised(self, environ) -> None:
        """Not an ``httpx.HTTPError``, so ``post_checkin`` lets it through."""
        bad = environ | {STATUS_URL_ENV: "http://[status.invalid:9000"}
        assert not backup.checkin("ok", {}, environ=bad)


# --- the entry point ---


class TestMain:
    @pytest.fixture
    def wired(self, monkeypatch, client):
        checkins: list[tuple[str, dict, str | None]] = []
        monkeypatch.setattr(backup.storage, "Client", lambda: client)
        monkeypatch.setattr(backup.subprocess, "run", FakePg())
        monkeypatch.setattr(
            backup,
            "checkin",
            lambda status, variables, *, fault=None, environ: checkins.append(
                (status, variables, fault)
            ),
        )
        monkeypatch.setenv(backup.BUCKET_ENV, BUCKET)
        return checkins

    def test_success_exits_zero_and_checks_in_ok(self, wired) -> None:
        assert backup.main(["--database", "archiver"]) == 0
        ((status, variables, fault),) = wired
        assert status == "ok"
        assert fault is None
        assert variables["outcome"] == "uploaded"

    def test_the_prefix_defaults_to_this_host(self, wired, bucket, monkeypatch) -> None:
        """A replacement host's own dumps land under its own name, never the
        timeline of the host it replaced."""
        monkeypatch.setattr(backup.socket, "gethostname", lambda: "co-registrar")
        assert backup.main([]) == 0
        (key,) = bucket.objects
        assert key.startswith("co-registrar/")

    def test_the_prefix_is_configuration(self, wired, bucket, monkeypatch) -> None:
        monkeypatch.setenv(backup.PREFIX_ENV, "rehearsal")
        assert backup.main([]) == 0
        (key,) = bucket.objects
        assert key.startswith("rehearsal/")

    def test_the_database_defaults_to_production(self, wired, monkeypatch) -> None:
        pg = FakePg()
        monkeypatch.setattr(backup.subprocess, "run", pg)
        assert backup.main([]) == 0
        (dump_call,) = [call for call in pg.calls if call[0] == "pg_dump"]
        assert "--dbname=archiver" in dump_call

    @pytest.mark.parametrize(
        "database",
        [
            "postgresql://u:s3cret@localhost/archiver",
            "postgresql://u@localhost/archiver?password=s3cret",
            "host=localhost password=s3cret dbname=archiver",
        ],
        ids=["url", "url-query", "conninfo"],
    )
    def test_a_password_on_the_command_line_is_refused(
        self, wired, monkeypatch, database, caplog
    ) -> None:
        """pg_dump and psql would carry it in /proc/<pid>/cmdline, mode 444
        (CONVENTIONS.md "Nor a command line"). Peer auth or PGPASSWORD."""
        pg = FakePg()
        monkeypatch.setattr(backup.subprocess, "run", pg)
        assert backup.main(["--database", database]) == 2
        assert pg.calls == []
        assert wired == []
        assert "s3cret" not in caplog.text

    def test_there_is_no_user_to_run_as(self, wired) -> None:
        """A job that holds no capability cannot drop to another user."""
        with pytest.raises(SystemExit):
            backup.main(["--run-as", "postgres"])

    def test_failure_exits_non_zero_and_checks_in_alert(self, wired, monkeypatch) -> None:
        monkeypatch.setattr(backup.subprocess, "run", FakePg(fail="pg_dump"))
        assert backup.main([]) == 1
        ((status, variables, fault),) = wired
        assert status == "alert"
        assert fault == "failed"
        assert "pg_dump" in variables["error"]

    def test_both_check_ins_name_the_host_the_same_way(self, wired, monkeypatch) -> None:
        """A monitor's alert template is written against these names."""
        assert backup.main([]) == 0
        monkeypatch.setattr(backup.subprocess, "run", FakePg(fail="pg_dump"))
        assert backup.main([]) == 1
        (_, ok, _), (_, alert, _) = wired
        assert ok["source_host"] == alert["source_host"]
        assert set(alert) == {"source_host", "outcome", "error"}

    def test_a_client_that_cannot_be_built_fails_before_the_dump(self, wired, monkeypatch) -> None:
        pg = FakePg()

        def no_key():
            raise DefaultCredentialsError("no key")

        monkeypatch.setattr(backup.subprocess, "run", pg)
        monkeypatch.setattr(backup.storage, "Client", no_key)
        assert backup.main([]) == 1
        ((status, variables, _),) = wired
        assert status == "alert"
        assert "DefaultCredentialsError" in variables["error"]
        assert pg.calls == []

    def test_a_key_path_outside_the_runs_credentials_is_refused_by_name(
        self, wired, monkeypatch, tmp_path
    ) -> None:
        """A stray ``GOOGLE_APPLICATION_CREDENTIALS`` beats the unit's ``%d/gcs``
        and aims the job at the root-only original. Built anyway, the client
        fails "Permission denied" on the key, which reads as an instruction to
        loosen its mode. So it is refused before the client is built."""
        built: list[int] = []
        monkeypatch.setattr(backup.storage, "Client", lambda: built.append(1))
        monkeypatch.setenv(backup.CREDENTIALS_DIRECTORY_ENV, str(tmp_path / "credentials"))
        monkeypatch.setenv(backup.KEY_PATH_ENV, "/etc/archiver/co-archiver-backup.json")
        assert backup.main([]) == 2
        assert built == []
        ((status, variables, fault),) = wired
        assert status == "alert"
        assert fault == "misconfigured"
        assert backup.KEY_PATH_ENV in variables["error"]

    def test_no_key_path_at_all_under_the_unit_is_refused(
        self, wired, monkeypatch, tmp_path
    ) -> None:
        """The unit's own line removed: the SDK would go looking for a key."""
        monkeypatch.setenv(backup.CREDENTIALS_DIRECTORY_ENV, str(tmp_path / "credentials"))
        monkeypatch.delenv(backup.KEY_PATH_ENV, raising=False)
        assert backup.main([]) == 2

    def test_the_runs_own_credential_copy_is_used(self, wired, monkeypatch, tmp_path) -> None:
        credentials = tmp_path / "credentials"
        monkeypatch.setenv(backup.CREDENTIALS_DIRECTORY_ENV, str(credentials))
        monkeypatch.setenv(backup.KEY_PATH_ENV, str(credentials / backup.GCS_CREDENTIAL))
        assert backup.main([]) == 0

    def test_no_bucket_is_a_failure_and_says_so(self, wired, monkeypatch) -> None:
        """No default bucket: guessing one is how bytes land where nobody reads."""
        monkeypatch.delenv(backup.BUCKET_ENV)
        assert backup.main([]) == 2
        ((status, variables, fault),) = wired
        assert status == "alert"
        assert fault == "misconfigured"
        assert backup.BUCKET_ENV in variables["error"]


class TestTestAlert:
    """``--test-alert`` proves the alert template through a real dispatch
    without a real failure (status#41 Q3, as drift's did on #32). co-status
    previews the template before recording, and notifier renders with
    ``StrictUndefined``: a missing variable is a 422 that records nothing."""

    @pytest.fixture
    def sent(self, monkeypatch) -> list[tuple[str, dict, str | None]]:
        sent: list[tuple[str, dict, str | None]] = []

        def record(status, variables, *, fault=None, environ):
            sent.append((status, dict(variables), fault))
            return True

        self.pg = FakePg()
        self.built: list[int] = []
        monkeypatch.setattr(backup, "checkin", record)
        monkeypatch.setattr(backup.subprocess, "run", self.pg)
        monkeypatch.setattr(backup.storage, "Client", lambda: self.built.append(1))
        return sent

    def test_sends_one_alert_carrying_every_template_variable(self, sent) -> None:
        assert backup.main(["--test-alert"]) == 0
        ((status, variables, fault),) = sent
        assert status == "alert"
        assert fault == "test"
        assert set(variables) == {"source_host", "outcome", "error"}
        assert variables["outcome"] == "test"
        assert "test alert" in variables["error"]

    def test_dumps_nothing_and_needs_no_bucket_or_key(self, sent, monkeypatch) -> None:
        monkeypatch.delenv(backup.BUCKET_ENV, raising=False)
        assert backup.main(["--test-alert"]) == 0
        assert self.pg.calls == []
        assert self.built == []

    def test_an_alert_status_did_not_take_exits_non_zero(self, monkeypatch) -> None:
        """Its whole purpose is the dispatch: a 422 or no monitor is a failure."""
        monkeypatch.setattr(backup, "checkin", lambda *a, **k: False)
        assert backup.main(["--test-alert"]) == 1


class TestMainThroughTheRealCheckin:
    """End to end through :func:`backup.checkin` and ``post_checkin``, Status
    stubbed: the shipped dump decides the exit code, never the check-in."""

    @pytest.fixture
    def unit_env(self, monkeypatch, client, tmp_path):
        credentials = _credentials(tmp_path)
        monkeypatch.setattr(backup.storage, "Client", lambda: client)
        monkeypatch.setattr(backup.subprocess, "run", FakePg())
        monkeypatch.setenv(backup.BUCKET_ENV, BUCKET)
        monkeypatch.setenv(backup.MONITOR_ID_ENV, MONITOR_ID)
        monkeypatch.setenv(backup.CREDENTIALS_DIRECTORY_ENV, str(credentials))
        # As the unit sets it: the key path is the run's own credential copy.
        monkeypatch.setenv(backup.KEY_PATH_ENV, str(credentials / backup.GCS_CREDENTIAL))

    @respx.mock
    def test_a_shipped_backup_checks_in_ok(self, unit_env, bucket) -> None:
        route = respx.post(CHECKIN_URL).mock(return_value=httpx.Response(202))
        assert backup.main([]) == 0
        body = json.loads(route.calls[0].request.content)
        assert body["status"] == "ok"
        assert body["variables"]["object"].startswith(f"gs://{BUCKET}/")
        assert len(bucket.objects) == 1

    @respx.mock
    def test_a_check_in_that_cannot_be_sent_never_fails_a_shipped_backup(
        self, unit_env, bucket
    ) -> None:
        respx.post(CHECKIN_URL).mock(side_effect=httpx.ConnectError("refused"))
        assert backup.main([]) == 0
        assert len(bucket.objects) == 1

    @respx.mock
    def test_a_check_in_that_cannot_be_sent_never_masks_a_failed_backup(
        self, unit_env, monkeypatch
    ) -> None:
        monkeypatch.setattr(backup.subprocess, "run", FakePg(fail="pg_dump"))
        respx.post(CHECKIN_URL).mock(return_value=httpx.Response(503))
        assert backup.main([]) == 1

    @respx.mock
    def test_without_a_monitor_the_backup_still_runs(self, unit_env, bucket, monkeypatch) -> None:
        monkeypatch.delenv(backup.MONITOR_ID_ENV)
        route = respx.post(url__regex=r".*").mock(return_value=httpx.Response(202))
        assert backup.main([]) == 0
        assert not route.called
        assert len(bucket.objects) == 1
