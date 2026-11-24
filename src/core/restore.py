"""Bring a shipped dump back (archiver#233).

Ported from CannObserv/watcher's ``src/ops/restore.py`` (watcher#296 D8). Three
steps, each refusing rather than guessing: **find** a dump (by key, or the
newest name under a host's prefix: names are timestamps); **fetch** it and prove
it is what the backup recorded (sha256 against the object's metadata, then the
same ``pg_restore`` reads the backup ran); **restore** it into an existing,
empty database, in one transaction, never ``--clean``, so a failure leaves
nothing half-loaded.

**The target is guarded before anything is fetched.** ``--into`` takes a
database whose name ``src.core.db_safety`` would call disposable (``_test`` or
``_dev``), or production only with ``--allow-production``; either way it must
be empty. A name the guard cannot read is refused.

The restore reads the archive on stdin, so ``postgres`` never needs to read a
file root wrote, and it preserves owners and grants: the dump carries the
tables' owner (``archiver``) and the read role's column grants (#348). It cannot
carry the roles themselves or the database's ``CONNECT`` grants; the runbook in
docs/BACKUP.md says what to recreate around it.

**Nothing newer than its target loads into it** (#509). Two majors can be newer
than the target server, and either fails the load partway, after the download:
the local ``pg_restore``, which writes its own session ``SET``s at load time
(none are in the archive), so a 17-or-later client's ``SET transaction_timeout``
reaches a 16 server (watcher#365: 18 against 16); and the archive's ``pg_dump``,
whose DDL an older server need not accept. So the target's major and the loading
client's are asked before the fetch, and the ``pg_dump`` major is read from the
fetched archive's own header, never the object's metadata. Same or older proceeds.

**The source host is always named.** A restore runs on a different host from
the one that shipped the dump, so the backup's default prefix (this hostname) is
the one prefix never wanted: once the new host's own timer has run it would
find a real, verifiable dump of the wrong database. ``--latest`` takes
``--prefix``; ``--list`` without one shows every host's dumps.

    python -m src.core.restore --list
    python -m src.core.restore --latest --prefix co-registrar --download-only /root/archiver-restore
    python -m src.core.restore --latest --prefix co-registrar --into archiver_restore_test \\
        --run-as postgres
"""

import argparse
import os
import re
import shlex
import stat
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import NamedTuple

from google.api_core.exceptions import NotFound
from google.cloud import storage

from src.core.backup import (
    BUCKET_ENV,
    KEY_TIME_FORMAT,
    LIST_TIMEOUT_SECONDS,
    OBJECT_SUFFIX,
    PG_DUMP_TIMEOUT_SECONDS,
    QUERY_TIMEOUT_SECONDS,
    UPLOAD_TIMEOUT_SECONDS,
    BackupError,
    Runner,
    Toc,
    password_in,
    sha256_file,
    tail,
    verify_dump,
)
from src.core.backup import iso as backup_iso
from src.core.db_safety import NON_PRODUCTION_SUFFIXES, database_name
from src.core.logging import configure_logging, get_logger

logger = get_logger("src.core.restore")

#: How far a dump's name may run ahead of the bucket's creation time for it:
#: the dumping host's clock is not the bucket's.
CLOCK_SKEW_TOLERANCE = timedelta(minutes=10)

# What `--list` prints beside each name, in this order.
_LISTED_METADATA = (
    "dumped_at",
    "alembic_head",
    "pg_dump_version",
    "server_version",
    "size_bytes",
    "source_host",
    "sha256",
)

#: The first number in a version as any PostgreSQL tool prints it: its major.
_MAJOR_RE = re.compile(r"\d+")

#: A bare database name, as ``--into archiver_restore_test`` gives it.
_PLAIN_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

#: Anything a dump could collide with: a relation outside the system schemas,
#: or a schema other than the empty ``public`` every new database has.
_CONTENT_QUERY = (
    "SELECT (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace"
    " WHERE n.nspname <> 'information_schema' AND n.nspname !~ '^pg_')"
    " + (SELECT count(*) FROM pg_namespace"
    " WHERE nspname NOT IN ('public', 'information_schema') AND nspname !~ '^pg_')"
)


class RestoreError(Exception):
    """Anything that means nothing was restored."""


def as_user(argv: list[str], run_as: str | None) -> list[str]:
    """Prefix ``argv`` to run as ``run_as`` via ``setpriv``; unchanged when None.

    The restore is run by hand as root (it reads the root-only key) and loads
    as ``postgres``. ``setpriv`` is a plain exec: it opens no PAM session, so it
    behaves the same from a login shell, ``sudo`` or a sandbox. ``--reset-env``
    hands the child only its passwd entry's ``HOME``/``SHELL``/``USER``/``LOGNAME``
    and a default ``PATH``, so nothing of the operator's root shell reaches a
    process any ``postgres``-uid process can read through ``/proc/<pid>/environ``.
    """
    if run_as is None:
        return argv
    return [
        "setpriv",
        f"--reuid={run_as}",
        f"--regid={run_as}",
        "--init-groups",
        "--reset-env",
        "--",
        *argv,
    ]


def pg_major(version: str | None) -> int | None:
    """The major of a PostgreSQL version as any tool prints it, or None.

    ``16`` from a TOC's ``16.15 (Ubuntu …)`` and from ``pg_restore --version``'s
    ``pg_restore (PostgreSQL) 16.15``.
    """
    match = _MAJOR_RE.search(version or "")
    return int(match.group()) if match else None


def _fields(values: Mapping[str, str | None], names: tuple[str, ...]) -> list[str]:
    """``name=value`` words, each value shell-quoted: versions hold spaces."""
    return [f"{name}={shlex.quote(values.get(name) or '')}" for name in names]


def _psql_scalar(database: str, query: str) -> list[str]:
    """``psql`` asking ``database`` one value, bare on stdout."""
    return [
        "psql",
        "--no-password",
        "--no-psqlrc",
        "--quiet",
        "--tuples-only",
        "--no-align",
        f"--dbname={database}",
        f"--command={query}",
    ]


def _under(prefix: str | None) -> str:
    """The listing prefix for a host's dumps; "" for the whole bucket."""
    return f"{prefix.strip('/')}/" if prefix else ""


class Snapshot(NamedTuple):
    """One shipped dump: its name, the metadata the backup wrote, and the
    bucket's own record of when the object was created."""

    name: str
    metadata: dict
    created: datetime | None

    @property
    def named_at(self) -> datetime | None:
        """The time the name claims; None for a name the backup never writes."""
        stamp = Path(self.name).name.removesuffix(OBJECT_SUFFIX)
        try:
            return datetime.strptime(stamp, KEY_TIME_FORMAT).replace(tzinfo=UTC)
        except ValueError:
            return None

    @property
    def suspect(self) -> bool:
        """Whether the name claims a time the bucket's own clock contradicts.

        An honest dump is named when ``pg_dump`` starts and created when the
        upload lands, so its name is never later than its creation, beyond
        clock skew. A later name is a skewed writer clock or a forgery, and a
        compromised writer planting ``2099…`` would otherwise own ``--latest``
        until the lifecycle rule removed it, 30 days on.
        """
        named_at = self.named_at
        if named_at is None or self.created is None:
            return True
        return named_at > self.created + CLOCK_SKEW_TOLERANCE


def list_snapshots(client: storage.Client, bucket: str, prefix: str | None) -> list[Snapshot]:
    """Every dump under ``prefix`` (every host's, if None), in name order, with
    the metadata the backup wrote. Within one host, name order is time order."""
    blobs = client.list_blobs(bucket, prefix=_under(prefix) or None, timeout=LIST_TIMEOUT_SECONDS)
    return sorted(
        (
            Snapshot(blob.name, dict(blob.metadata or {}), blob.time_created)
            for blob in blobs
            if blob.name.endswith(OBJECT_SUFFIX)
        ),
        key=lambda snapshot: snapshot.name,
    )


def latest_key(client: storage.Client, bucket: str, prefix: str) -> str:
    """The newest dump the named host shipped, passing over suspect names."""
    snapshots = list_snapshots(client, bucket, prefix)
    suspect = [snapshot.name for snapshot in snapshots if snapshot.suspect]
    if suspect:
        logger.warning(
            "Passing over dumps named later than the bucket created them, a skewed "
            "clock or a forgery: %s",
            ", ".join(suspect),
        )
    candidates = [snapshot for snapshot in snapshots if not snapshot.suspect]
    if not candidates:
        passed = f" (passed over {len(suspect)} suspect)" if suspect else ""
        raise RestoreError(f"no dumps under gs://{bucket}/{_under(prefix)}{passed}")
    return candidates[-1].name


def _private_dir(dest_dir: Path) -> None:
    """Create ``dest_dir`` 0700, or accept an existing one only if it is this
    user's own, a real directory, and closed to everyone else.

    The fetch runs as root and writes the whole production database, personal
    data included: a directory another user made first would let them read it,
    or plant a link for root to write through.
    """
    dest_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    st = dest_dir.lstat()
    if not stat.S_ISDIR(st.st_mode):
        raise RestoreError(f"{dest_dir} is not a directory; refusing it")
    if st.st_uid != os.geteuid():
        raise RestoreError(f"{dest_dir} is owned by uid {st.st_uid}, not this user; refusing it")
    if st.st_mode & 0o077:
        raise RestoreError(
            f"{dest_dir} is not private (mode {stat.S_IMODE(st.st_mode):o}); "
            "use a new directory, or chmod 700 it"
        )


class Fetched(NamedTuple):
    """A verified download, and what its own header says (``pg_restore --list``)."""

    path: Path
    toc: Toc


def fetch(
    client: storage.Client, bucket: str, key: str, dest_dir: Path, *, runner: Runner
) -> Fetched:
    """Download ``key`` into ``dest_dir`` and prove it is the dump that was shipped.

    The file is created ``O_EXCL | O_NOFOLLOW`` at 0600 in a private directory,
    so nothing already at the name (a stale dump, a planted link) is written
    through, and no other user can read the result. A failed fetch removes it.
    """
    blob = client.bucket(bucket).get_blob(key, timeout=LIST_TIMEOUT_SECONDS)
    if blob is None:
        raise RestoreError(f"gs://{bucket}/{key} not found")
    expected = (blob.metadata or {}).get("sha256")
    if not expected:
        raise RestoreError(f"gs://{bucket}/{key} carries no recorded sha256; refusing it")
    _private_dir(dest_dir)
    path = dest_dir / Path(key).name
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError as e:
        raise RestoreError(f"{path} already exists; refusing to write over it") from e
    try:
        with os.fdopen(fd, "wb") as handle:
            try:
                blob.download_to_file(handle, timeout=UPLOAD_TIMEOUT_SECONDS)
            except NotFound as e:
                raise RestoreError(f"gs://{bucket}/{key} not found") from e
        actual = sha256_file(path)
        if actual != expected:
            raise RestoreError(f"{key}: sha256 {actual} does not match the recorded {expected}")
        try:
            toc = verify_dump(path, runner=runner)
        except BackupError as e:
            raise RestoreError(str(e)) from e
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return Fetched(path, toc)


def production_refusal(database: str, *, allow_production: bool) -> str | None:
    """Why ``--into database`` is refused by name; None when it may proceed.

    ``db_safety``'s boundary: a ``_test`` or ``_dev`` suffix is disposable,
    anything else is production and needs ``--allow-production``. A name that
    cannot be read (neither a plain name nor a URL naming one) fails closed,
    override or not.
    """
    name = database_name(database) if "://" in database else database
    if not name or not _PLAIN_NAME.fullmatch(name):
        return f"cannot read a database name from {database!r}; give a plain name or a URL"
    if name.endswith(NON_PRODUCTION_SUFFIXES) or allow_production:
        return None
    return (
        f"{name!r} carries no {' or '.join(NON_PRODUCTION_SUFFIXES)} suffix, so it is treated "
        "as production; restore into a scratch database first, or pass --allow-production"
    )


def assert_empty(database: str, *, run_as: str | None, runner: Runner) -> None:
    """Refuse a target that holds anything a dump could collide with.

    Never ``--clean``: a restore adds to nothing. Asked first, before anything
    is fetched, and as the user that will restore, so it also proves the
    database exists and that user can reach it.
    """
    argv = as_user(_psql_scalar(database, _CONTENT_QUERY), run_as)
    result = runner(
        argv, capture_output=True, text=True, check=False, timeout=QUERY_TIMEOUT_SECONDS
    )
    if result.returncode != 0:
        raise RestoreError(f"psql could not inspect the target: {tail(result.stderr)}")
    count = result.stdout.strip()
    if count != "0":
        raise RestoreError(
            f"the target is not empty ({count} schemas and relations); restore only into a "
            "new database (createdb), never over one"
        )


def target_major(database: str, *, run_as: str | None, runner: Runner) -> int:
    """The target server's major, asked as the user the restore loads as."""
    argv = as_user(_psql_scalar(database, "SHOW server_version_num"), run_as)
    result = runner(
        argv, capture_output=True, text=True, check=False, timeout=QUERY_TIMEOUT_SECONDS
    )
    if result.returncode != 0:
        raise RestoreError(
            f"psql could not ask the target its server version: {tail(result.stderr)}"
        )
    answer = (result.stdout or "").strip()
    if not answer.isdigit():
        raise RestoreError(f"the target answered {answer!r} for its server version")
    return int(answer) // 10000


def client_major(database: str, *, run_as: str | None, runner: Runner) -> int:
    """The major of the ``pg_restore`` the load will run, asked as the user it runs as.

    Ubuntu's pg_wrapper picks the binary from that user's environment and
    cluster map, and from the arguments (``service=``), so the probe goes
    through the same ``as_user`` and carries the load's ``--dbname``.
    ``--version`` comes first: ``pg_restore`` answers it only as ``argv[1]``,
    before reading the rest, and rejects it anywhere else.
    """
    argv = as_user(["pg_restore", "--version", f"--dbname={database}"], run_as)
    result = runner(
        argv, capture_output=True, text=True, check=False, timeout=QUERY_TIMEOUT_SECONDS
    )
    if result.returncode != 0:
        raise RestoreError(
            f"pg_restore --version exited {result.returncode}: {tail(result.stderr)}"
        )
    major = pg_major(result.stdout)
    if major is None:
        answer = (result.stdout or "").strip()
        raise RestoreError(f"pg_restore --version named no version ({answer!r})")
    return major


def check_client(client: int, target: int) -> None:
    """Refuse a ``pg_restore`` newer than the target server's major.

    It writes its own session ``SET``s, and a newer one writes settings an
    older server rejects: 17's ``transaction_timeout`` against 16.
    """
    if client > target:
        raise RestoreError(
            f"the local pg_restore {client} is newer than the target's PostgreSQL {target}, "
            "which would reject the settings it writes partway through; load with "
            f"postgresql-client-{target}'s pg_restore (Ubuntu's pg_wrapper runs the local "
            "cluster's major, else the newest installed) or into a PostgreSQL "
            f"{client} or newer server"
        )


def check_compatible(toc: Toc, target: int) -> None:
    """Refuse an archive written by a newer ``pg_dump`` major than ``target``.

    Read from the archive's own header, never the object's metadata, which a
    re-upload could rewrite. An absent or unreadable version refuses too: every
    custom-format header carries it. Only ``pg_dump``'s: it refuses to dump a
    newer server, so the archive's ``server_version`` is never the newer one.
    """
    dumped_by = pg_major(toc.pg_dump_version)
    if dumped_by is None:
        raise RestoreError(
            f"the archive names no pg_dump version ({toc.pg_dump_version!r}); refusing it"
        )
    if dumped_by > target:
        raise RestoreError(
            f"the archive was written by pg_dump {dumped_by} ({toc.pg_dump_version}), "
            f"newer than the target's PostgreSQL {target}, which need not accept what it "
            f"wrote; restore into a PostgreSQL {dumped_by} or newer server"
        )


def restore_into(path: Path, database: str, *, run_as: str | None, runner: Runner) -> None:
    """Load ``path`` into ``database``, all or nothing."""
    argv = as_user(
        [
            "pg_restore",
            "--no-password",
            "--exit-on-error",
            "--single-transaction",
            f"--dbname={database}",
        ],
        run_as,
    )
    with path.open("rb") as handle:
        result = runner(
            argv,
            stdin=handle,
            capture_output=True,
            text=True,
            check=False,
            timeout=PG_DUMP_TIMEOUT_SECONDS,
        )
    if result.returncode != 0:
        raise RestoreError(f"pg_restore exited {result.returncode}: {tail(result.stderr)}")


def main(argv: list[str] | None = None, *, environ: Mapping[str, str] = os.environ) -> int:
    """Operator entrypoint; see the module docstring. 0 done, 1 failed, 2 usage."""
    parser = argparse.ArgumentParser(description="Restore an Archiver database dump from GCS")
    which = parser.add_mutually_exclusive_group(required=True)
    which.add_argument("--list", action="store_true", help="list dumps and exit")
    which.add_argument("--latest", action="store_true", help="the newest dump")
    which.add_argument("--object", metavar="KEY", help="a dump by its object key")
    where = parser.add_mutually_exclusive_group()
    where.add_argument("--into", metavar="DATABASE", help="restore into this empty database")
    where.add_argument("--download-only", metavar="DIR", type=Path, help="fetch and verify only")
    parser.add_argument(
        "--prefix",
        metavar="HOST",
        default=None,
        help="the host whose dumps to use (required with --latest; never this host's by default)",
    )
    parser.add_argument("--run-as", default=None, help="OS user for psql/pg_restore (peer auth)")
    parser.add_argument(
        "--allow-production",
        action="store_true",
        help="let --into name a database without a _test/_dev suffix",
    )
    args = parser.parse_args(argv)

    configure_logging()
    bucket = environ.get(BUCKET_ENV)
    if not bucket:
        print(f"{BUCKET_ENV} not set", file=sys.stderr)
        return 2
    if args.latest and not args.prefix:
        print(
            "say whose: --latest needs --prefix HOST, the host that shipped the dump "
            "(--list shows every host's)",
            file=sys.stderr,
        )
        return 2
    if args.into and password_in(args.into):
        print(
            "refused: --into carries a password, which argv would expose; "
            "use a plain name and peer auth (--run-as postgres)",
            file=sys.stderr,
        )
        return 2
    if args.allow_production and not args.into:
        print("--allow-production goes only with --into", file=sys.stderr)
        return 2
    if args.into and (
        refusal := production_refusal(args.into, allow_production=args.allow_production)
    ):
        print(f"refused: {refusal}", file=sys.stderr)
        return 2

    try:
        # Inside the try: a missing or revoked key raises from google.auth here.
        client = storage.Client()
        if args.list:
            snapshots = list_snapshots(client, bucket, args.prefix)
            for snapshot in snapshots:
                created = backup_iso(snapshot.created) if snapshot.created else ""
                print(
                    snapshot.name,
                    *_fields(snapshot.metadata, _LISTED_METADATA),
                    f"created={created}",
                    *(["SUSPECT(named after the bucket created it)"] if snapshot.suspect else []),
                )
            if not snapshots:
                print(f"no dumps under gs://{bucket}/{_under(args.prefix)}", file=sys.stderr)
            return 0
        if not (args.into or args.download_only):
            print("say where: --into DATABASE or --download-only DIR", file=sys.stderr)
            return 2
        if args.download_only:
            key = args.object or latest_key(client, bucket, args.prefix)
            fetched = fetch(client, bucket, key, args.download_only, runner=subprocess.run)
            print(f"verified: {fetched.path}")
            header = {
                "pg_dump_version": fetched.toc.pg_dump_version,
                "server_version": fetched.toc.server_version,
            }
            print("archive:", *_fields(header, tuple(header)))
            return 0
        assert_empty(args.into, run_as=args.run_as, runner=subprocess.run)
        # Before the fetch: a client newer than the target fails in seconds,
        # not after the download (#509).
        target = target_major(args.into, run_as=args.run_as, runner=subprocess.run)
        check_client(client_major(args.into, run_as=args.run_as, runner=subprocess.run), target)
        key = args.object or latest_key(client, bucket, args.prefix)
        with tempfile.TemporaryDirectory(prefix="archiver-restore-") as work:
            fetched = fetch(client, bucket, key, Path(work), runner=subprocess.run)
            check_compatible(fetched.toc, target)
            restore_into(fetched.path, args.into, run_as=args.run_as, runner=subprocess.run)
    except Exception as e:
        # One exit and one sentence for every failure, whatever raised it:
        # google.auth's RefreshError, the listing's Forbidden, the download's
        # DataCorruption and a wedged pg_restore's TimeoutExpired are none of
        # them a RestoreError, and a traceback is the wrong thing to hand an
        # operator mid-incident.
        error = str(e) if isinstance(e, RestoreError) else f"{type(e).__name__}: {e}"
        logger.error("Restore failed: %s", error)
        print(f"restore failed: {error}", file=sys.stderr)
        return 1
    print(f"restored gs://{bucket}/{key} into {args.into}")
    print(
        "next: re-apply the read role's grants and scripts/setup-backup-role.sql, "
        "then the checks, as docs/BACKUP.md § Restore shows"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
