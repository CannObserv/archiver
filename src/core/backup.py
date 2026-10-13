"""Ship Archiver's database to a bucket, nightly (archiver#233).

Until this, production had no backup of any kind: no timer, no cron, and
``archive_mode`` off. Ported from CannObserv/watcher's ``src/ops/backup.py``
(watcher#296 D8, #297), itself on CannObserv/broker#4's pattern, and built to be
dumb in the ways that keep a backup honest:

- **It holds no database credential, and no privilege.** The unit runs as its
  own system user, ``archiver_backup``, with no capabilities; ``pg_dump`` and
  the ``psql`` that reads the schema version connect as that user over the
  local socket, by peer auth, to the role of the same name, which holds
  ``pg_read_all_data`` and ``CONNECT`` on ``archiver`` and nothing else
  (``scripts/setup-backup-role.sql``). Not ``exedev``: its #348 column allowlist
  would make the dump silently incomplete. Not ``archiver``: the owner role can
  write. The keys arrive as systemd credentials. Tests pass a DSN instead.
- **It verifies before it ships.** ``pg_restore --list`` must read the archive
  and find the data sections of ``information.alembic_version`` and
  ``information.info_items``: a readable dump of the wrong database is refused.
  Then every data block is read through, since a truncated archive still lists.
- **It never queues behind a migration.** ``--lock-wait-timeout`` fails the
  dump rather than wait on a lock; a migration that meets the dump's ACCESS
  SHARE fails on its own ``lock_timeout`` and is rerun.
- **The object is named by the dump's start time**, when ``pg_dump`` took its
  snapshot, so a listing is a timeline and the newest name is the newest data.
- **It creates, and never overwrites or deletes.** ``if_generation_match=0`` in
  code; ``objectCreator`` + ``objectViewer`` and no ``delete`` at IAM; retention
  is the bucket's lifecycle rule. Two dumps are never the same bytes, so a 412
  is ``unchanged`` only when the object's recorded sha256 matches; otherwise it
  is a name collision, and a failure.
- **Failure is loud, and so is silence.** A failed run is a failed unit and an
  ``alert`` check-in to co-status's ``co-archiver-backup``; a shipped one checks
  in ``ok``; the monitor alarms when neither arrives. :func:`checkin` never
  raises: the dump decides the exit code, never the monitoring path.

Restore is :mod:`src.core.restore`; docs/BACKUP.md is
the runbook around both.
"""

import argparse
import hashlib
import os
import re
import socket
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from google.api_core.exceptions import NotFound, PreconditionFailed
from google.cloud import storage

from src.core.logging import configure_logging, get_logger
from src.core.status_checkin import (
    CREDENTIAL_NAME,
    DEFAULT_STATUS_URL,
    MONITOR_ID_PATTERN,
    STATUS_URL_ENV,
    post_checkin,
    read_key,
)

# Literal rather than __name__: the timer runs this module via ``python -m``.
logger = get_logger("src.core.backup")

BUCKET_ENV = "ARCHIVER_BACKUP_BUCKET"
PREFIX_ENV = "ARCHIVER_BACKUP_PREFIX"
#: co-archiver-backup, tenant co-archiver; absent until co-status creates it.
MONITOR_ID_ENV = "CO_ARCHIVER_BACKUP_MONITOR_ID"
#: Where the GCS SDK finds its key. The unit sets it to its credential copy.
KEY_PATH_ENV = "GOOGLE_APPLICATION_CREDENTIALS"
CREDENTIALS_DIRECTORY_ENV = "CREDENTIALS_DIRECTORY"
#: The ``LoadCredential=`` name ``archiver-backup.service`` gives the GCS key.
GCS_CREDENTIAL = "gcs"
DEFAULT_DATABASE = "archiver"
OBJECT_SUFFIX = ".dump"
# Basic-format ISO 8601, UTC. Sorts as it reads, and no ':' for a shell to trip on.
KEY_TIME_FORMAT = "%Y%m%dT%H%M%SZ"
CONTENT_TYPE = "application/octet-stream"

#: A dump that lacks either data section is not a backup of this database.
REQUIRED_TABLES = ("information.alembic_version", "information.info_items")

# Bounds on the slow calls. The database was about 9 MB when this was written
# (2026-10-13); these are generous for that and short enough that a wedged call
# is a failed unit rather than a hang.
PG_DUMP_TIMEOUT_SECONDS = 1800
QUERY_TIMEOUT_SECONDS = 60
UPLOAD_TIMEOUT_SECONDS = 600.0
LIST_TIMEOUT_SECONDS = 30.0
#: How long the dump waits for a table lock before it gives up.
LOCK_WAIT_TIMEOUT = "30s"

_HEADER_RE = re.compile(r"^;\s+(Dumped from database version|Dumped by pg_dump version): (.+)$")
_ENTRIES_RE = re.compile(r"^;\s+TOC Entries: (\d+)$")
_TABLE_DATA_RE = re.compile(r"^\d+; \d+ \d+ TABLE DATA (\S+) (\S+) ")

Runner = Callable[..., subprocess.CompletedProcess]


class BackupError(Exception):
    """Anything that means the dump was not shipped."""


@dataclass(frozen=True)
class Toc:
    """What ``pg_restore --list`` says about an archive."""

    server_version: str | None = None
    pg_dump_version: str | None = None
    entries: int | None = None
    tables_with_data: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class Dump:
    """A verified dump on local disk, and what it says about itself."""

    path: Path
    size_bytes: int
    sha256: str
    dumped_at: datetime
    alembic_head: str | None
    toc: Toc


# --- pure ---


def parse_toc(text: str) -> Toc:
    """The header fields and the tables with a data section."""
    versions: dict[str, str] = {}
    entries: int | None = None
    tables: set[str] = set()
    for line in text.splitlines():
        if match := _HEADER_RE.match(line):
            versions[match.group(1)] = match.group(2).strip()
        elif match := _ENTRIES_RE.match(line):
            entries = int(match.group(1))
        elif match := _TABLE_DATA_RE.match(line):
            tables.add(f"{match.group(1)}.{match.group(2)}")
    return Toc(
        server_version=versions.get("Dumped from database version"),
        pg_dump_version=versions.get("Dumped by pg_dump version"),
        entries=entries,
        tables_with_data=frozenset(tables),
    )


def object_key(prefix: str, dumped_at: datetime) -> str:
    """``<prefix>/<UTC basic ISO 8601>.dump``."""
    stamp = dumped_at.astimezone(UTC).strftime(KEY_TIME_FORMAT)
    return f"{prefix.strip('/')}/{stamp}{OBJECT_SUFFIX}"


def iso(at: datetime) -> str:
    """ISO 8601, UTC, second precision, ``Z``."""
    return at.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def misplaced_key(environ: Mapping[str, str]) -> str | None:
    """Why the GCS key path is not this run's credential copy; None when it is.

    Under the unit the path is ``%d/gcs``, the private copy systemd made. A
    value from anywhere else (a drop-in, an ``EnvironmentFile=`` someone adds)
    aims the job at the root-only original, and the SDK fails "Permission
    denied" on it, which reads as a reason to loosen the key's mode. Outside a
    unit with credentials (a test, a hand run) there is no copy to compare.
    """
    directory = environ.get(CREDENTIALS_DIRECTORY_ENV, "").strip()
    if not directory:
        return None
    key = environ.get(KEY_PATH_ENV, "").strip()
    if key and Path(key).is_relative_to(directory):
        return None
    return (
        f"{KEY_PATH_ENV} is {key!r}, not this run's credential copy under {directory}: "
        f"only the unit's own Environment={KEY_PATH_ENV}=%d/{GCS_CREDENTIAL} may set it"
    )


def sha256_file(path: Path) -> str:
    """Hex sha256 of a file, read in 1 MiB chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tail(text: str | bytes | None) -> str:
    """A command's last three lines of stderr, on one line."""
    if isinstance(text, bytes):
        text = text.decode(errors="replace")
    return " | ".join((text or "").strip().splitlines()[-3:])


# --- effects on the database and the file ---


def read_alembic_head(database: str, *, runner: Runner) -> str | None:
    """The schema version, recorded so a restore can be checked against it."""
    argv = [
        "psql",
        "--no-password",
        "--no-psqlrc",
        "--quiet",
        "--tuples-only",
        "--no-align",
        f"--dbname={database}",
        "--command=SELECT version_num FROM information.alembic_version",
    ]
    result = runner(
        argv, capture_output=True, text=True, check=False, timeout=QUERY_TIMEOUT_SECONDS
    )
    if result.returncode != 0:
        raise BackupError(f"psql could not read alembic_version: {tail(result.stderr)}")
    return result.stdout.strip() or None


def run_pg_dump(database: str, out: Path, *, runner: Runner) -> None:
    """Custom format to ``out``, through an fd this process opened."""
    argv = [
        "pg_dump",
        "--format=custom",
        "--no-password",
        f"--lock-wait-timeout={LOCK_WAIT_TIMEOUT}",
        f"--dbname={database}",
    ]
    with out.open("wb") as handle:
        result = runner(
            argv,
            stdout=handle,
            stderr=subprocess.PIPE,
            check=False,
            timeout=PG_DUMP_TIMEOUT_SECONDS,
        )
    if result.returncode != 0:
        raise BackupError(f"pg_dump exited {result.returncode}: {tail(result.stderr)}")


def verify_dump(path: Path, *, runner: Runner) -> Toc:
    """Refuse an archive ``pg_restore`` cannot read, or one of the wrong database.

    Two reads. ``--list`` reads the header and the table of contents, which
    says whose database it is. But custom format writes that table before the
    data, so a truncated archive lists cleanly, and a second read,
    ``--file=/dev/null``, decompresses every data block through to the end.
    """
    result = runner(
        ["pg_restore", "--list", str(path)],
        capture_output=True,
        text=True,
        check=False,
        timeout=QUERY_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise BackupError(f"pg_restore --list rejected {path.name}: {tail(result.stderr)}")
    toc = parse_toc(result.stdout)
    missing = [table for table in REQUIRED_TABLES if table not in toc.tables_with_data]
    if missing:
        raise BackupError(f"dump has no data for {', '.join(missing)}; refusing to ship it")
    full = runner(
        ["pg_restore", "--file=/dev/null", str(path)],
        capture_output=True,
        text=True,
        check=False,
        timeout=PG_DUMP_TIMEOUT_SECONDS,
    )
    if full.returncode != 0:
        raise BackupError(f"pg_restore could not read {path.name} through: {tail(full.stderr)}")
    return toc


def take_dump(
    database: str,
    workdir: Path,
    *,
    runner: Runner,
    now: Callable[[], datetime],
) -> Dump:
    """Dump, verify, describe. The start time names it: ``pg_dump`` takes its
    snapshot as it begins."""
    dumped_at = now().astimezone(UTC).replace(microsecond=0)
    alembic_head = read_alembic_head(database, runner=runner)
    workdir.mkdir(parents=True, exist_ok=True)
    path = workdir / "archiver.dump"
    run_pg_dump(database, path, runner=runner)
    toc = verify_dump(path, runner=runner)
    return Dump(
        path=path,
        size_bytes=path.stat().st_size,
        sha256=sha256_file(path),
        dumped_at=dumped_at,
        alembic_head=alembic_head,
        toc=toc,
    )


# --- effects on the bucket ---


def preflight(client: storage.Client, bucket: str, prefix: str) -> None:
    """Prove the bucket is there and listable by this identity.

    A one-object listing, not ``exists()``: the SDK swallows a missing bucket's
    404 and returns ``False``, which is exactly the misconfiguration this check
    exists to catch (replicator#7 CR #1). The listing is lazy, so it is advanced.
    """
    listing = client.list_blobs(
        bucket, max_results=1, prefix=f"{prefix.strip('/')}/", timeout=LIST_TIMEOUT_SECONDS
    )
    try:
        next(iter(listing), None)
    except NotFound as e:
        raise BackupError(f"bucket {bucket!r} not found, or not listable: {e}") from e


def upload(client: storage.Client, bucket: str, key: str, dump: Dump, *, host: str) -> str:
    """Create the object; ``unchanged`` only if this very dump is already there."""
    blob = client.bucket(bucket).blob(key)
    blob.metadata = {
        "dumped_at": iso(dump.dumped_at),
        "sha256": dump.sha256,
        "size_bytes": str(dump.size_bytes),
        "alembic_head": dump.alembic_head or "",
        "server_version": dump.toc.server_version or "",
        "pg_dump_version": dump.toc.pg_dump_version or "",
        "toc_entries": "" if dump.toc.entries is None else str(dump.toc.entries),
        "source_host": host,
    }
    try:
        blob.upload_from_filename(
            str(dump.path),
            content_type=CONTENT_TYPE,
            if_generation_match=0,
            timeout=UPLOAD_TIMEOUT_SECONDS,
        )
    except PreconditionFailed:
        existing = client.bucket(bucket).get_blob(key, timeout=LIST_TIMEOUT_SECONDS)
        if existing is None:
            raise BackupError(f"{key} already exists, and could not be read back") from None
        if (existing.metadata or {}).get("sha256") == dump.sha256:
            return "unchanged"
        raise BackupError(f"{key} already exists with different contents") from None
    return "uploaded"


# --- the check-in ---


def checkin(
    status: Literal["ok", "alert"],
    variables: Mapping[str, object],
    *,
    fault: str | None = None,
    environ: Mapping[str, str],
) -> bool:
    """One check-in to ``co-archiver-backup``; True when Status took it.

    **Never raises.** Whatever goes wrong here is logged and swallowed: a
    shipped dump stays a successful unit, a failed one stays failed, and a
    check-in that never lands is what the dead-man monitor exists to notice.
    No monitor id is a warning, not an error: the unit runs without one until
    co-status creates the monitor.
    """
    monitor_id = environ.get(MONITOR_ID_ENV, "").strip()
    if not monitor_id:
        logger.warning(
            "No %s: no check-in sent, and a backup that stops will not be noticed",
            MONITOR_ID_ENV,
        )
        return False
    if not MONITOR_ID_PATTERN.fullmatch(monitor_id):
        logger.error("Check-in not sent: %s is not a ULID", MONITOR_ID_ENV)
        return False
    credentials = environ.get(CREDENTIALS_DIRECTORY_ENV, "").strip()
    key = read_key(Path(credentials) if credentials else None)
    if not key:
        logger.error("Check-in not sent: no %s credential", CREDENTIAL_NAME)
        return False
    try:
        post_checkin(
            environ.get(STATUS_URL_ENV) or DEFAULT_STATUS_URL,
            monitor_id,
            key,
            status,
            {name: "" if value is None else str(value) for name, value in variables.items()},
            metadata={"fault": fault} if fault else None,
        )
    except Exception as e:  # CheckinFailed, or anything httpx raises outside HTTPError
        logger.error("Check-in %s failed: %s", status, f"{type(e).__name__}: {e}")
        return False
    return True


# --- orchestration ---


def run_backup(
    *,
    database: str,
    bucket: str,
    prefix: str,
    client: storage.Client,
    workdir: Path,
    runner: Runner | None = None,
    host: str | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict:
    """One run: preflight, dump, verify, create. Returns the summary it logged.

    The bucket is checked first: it is the cheap call, and a misspelled one
    should fail before it costs a ``pg_dump`` of production.

    ``runner`` defaults to ``subprocess.run`` looked up at call time, not bound
    as a default, so a test that replaces it can never fall through to the
    real binaries.

    Raises ``BackupError`` for any failure, whatever its type: a revoked key
    surfaces from google.auth as a ``RefreshError``, a transport fault as a
    ``TransportError``, neither a ``GoogleAPICallError`` (broker#4's review).
    """
    host = host or socket.gethostname()
    runner = runner if runner is not None else subprocess.run
    try:
        preflight(client, bucket, prefix)
        dump = take_dump(database, workdir, runner=runner, now=now)
        key = object_key(prefix, dump.dumped_at)
        outcome = upload(client, bucket, key, dump, host=host)
    except Exception as e:
        error = str(e) if isinstance(e, BackupError) else f"{type(e).__name__}: {e}"
        logger.error("Backup failed: %s", error, extra={"bucket": bucket})
        raise BackupError(error) from e
    summary = {
        "outcome": outcome,
        "object": f"gs://{bucket}/{key}",
        "dumped_at": iso(dump.dumped_at),
        "size_bytes": dump.size_bytes,
        "sha256": dump.sha256,
        "alembic_head": dump.alembic_head,
        "source_host": host,
    }
    logger.info("Backup %s %s", outcome, summary["object"], extra=summary)
    return summary


def main(argv: list[str] | None = None, *, environ: Mapping[str, str] = os.environ) -> int:
    """Timer entrypoint. Exit 0 only when the dump is in the bucket; 1 when it
    is not; 2 for invalid settings. The check-in never changes the code."""
    parser = argparse.ArgumentParser(description="Archiver database dump to GCS (archiver#233)")
    parser.add_argument("--database", default=DEFAULT_DATABASE, help="name, or a DSN in tests")
    args = parser.parse_args(argv)

    configure_logging()
    host = socket.gethostname()

    def fail(code: int, error: str, fault: str) -> int:
        # The variables a monitor's alert template can use; DEPLOYMENT.md lists them.
        variables = {"source_host": host, "outcome": "failed", "error": error}
        checkin("alert", variables, fault=fault, environ=environ)
        return code

    bucket = environ.get(BUCKET_ENV)
    if not bucket:
        # No default bucket: guessing one is how bytes land where nobody reads.
        logger.error("%s not set: nowhere to ship the dump", BUCKET_ENV)
        return fail(2, f"{BUCKET_ENV} not set", "misconfigured")
    # This host's name by default: a replacement host's own dumps never join
    # the timeline of the host it replaced.
    prefix = environ.get(PREFIX_ENV) or host
    if misplaced := misplaced_key(environ):
        logger.error("%s; not starting", misplaced)
        return fail(2, misplaced, "misconfigured")

    with tempfile.TemporaryDirectory(prefix="archiver-backup-") as work:
        try:
            # Built first, so a missing or unreadable key fails before the dump.
            client = storage.Client()
        except Exception as e:  # google.auth raises its own hierarchy
            error = f"{type(e).__name__}: {e}"
            logger.error("Backup failed before it could start: %s", error)
            return fail(1, error, "failed")
        try:
            summary = run_backup(
                database=args.database,
                bucket=bucket,
                prefix=prefix,
                client=client,
                workdir=Path(work),
                host=host,
            )
        except BackupError as e:
            return fail(1, str(e), "failed")
    checkin("ok", summary, environ=environ)
    return 0


if __name__ == "__main__":
    sys.exit(main())
