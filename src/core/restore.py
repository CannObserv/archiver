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
_LISTED_METADATA = ("dumped_at", "alembic_head", "size_bytes", "source_host", "sha256")

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


def fetch(client: storage.Client, bucket: str, key: str, dest_dir: Path, *, runner: Runner) -> Path:
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
            verify_dump(path, runner=runner)
        except BackupError as e:
            raise RestoreError(str(e)) from e
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return path


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
    argv = as_user(
        [
            "psql",
            "--no-password",
            "--no-psqlrc",
            "--quiet",
            "--tuples-only",
            "--no-align",
            f"--dbname={database}",
            f"--command={_CONTENT_QUERY}",
        ],
        run_as,
    )
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
                    *(f"{name}={snapshot.metadata.get(name, '')}" for name in _LISTED_METADATA),
                    f"created={created}",
                    *(["SUSPECT(named after the bucket created it)"] if snapshot.suspect else []),
                )
            if not snapshots:
                print(f"no dumps under gs://{bucket}/{_under(args.prefix)}", file=sys.stderr)
            return 0
        if not (args.into or args.download_only):
            print("say where: --into DATABASE or --download-only DIR", file=sys.stderr)
            return 2
        if args.into:
            assert_empty(args.into, run_as=args.run_as, runner=subprocess.run)
        key = args.object or latest_key(client, bucket, args.prefix)
        if args.download_only:
            path = fetch(client, bucket, key, args.download_only, runner=subprocess.run)
            print(f"verified: {path}")
            return 0
        with tempfile.TemporaryDirectory(prefix="archiver-restore-") as work:
            path = fetch(client, bucket, key, Path(work), runner=subprocess.run)
            restore_into(path, args.into, run_as=args.run_as, runner=subprocess.run)
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
