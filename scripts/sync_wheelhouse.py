"""Mirror the private cannobserv package index into the local wheelhouse.

Downloads every object under ``gs://co-gcs-pypi/wheels/`` into ``./.wheelhouse``
(repo root), skipping any file already present with a matching size. ``uv``
then resolves ``co-core`` / ``co-core-aio`` from that directory via the
``[tool.uv] find-links`` entry in ``pyproject.toml`` (archiver#72 / #75).

Runs standalone, *before* ``uv sync`` — it must not import the project (whose
deps are what the wheelhouse provides), so invoke it in an isolated env:

    uv run --no-project --with google-cloud-storage python scripts/sync_wheelhouse.py

Authentication is Application Default Credentials. On the VM/deploy that is the
service-account key at ``GOOGLE_APPLICATION_CREDENTIALS`` (set in
``/etc/archiver/.env``); in CI it is the ADC file written by
``google-github-actions/auth`` (keyless Workload Identity Federation). Either
way the identity needs only ``roles/storage.objectViewer`` on the bucket.

Exit codes: ``0`` success (including a no-op re-run) · ``1`` failure (auth,
network, or a missing bucket). The unit runs this as a non-fatal
``ExecStartPre`` (``-`` prefix): a transient failure is logged, and if the
wheelhouse is already populated the service still starts — only a genuinely
missing wheel surfaces later as a hard ``uv`` resolution error.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from google.cloud import storage

BUCKET = os.environ.get("ARCHIVER_WHEELHOUSE_BUCKET", "co-gcs-pypi")
PREFIX = os.environ.get("ARCHIVER_WHEELHOUSE_PREFIX", "wheels/")
DEST = Path(__file__).resolve().parent.parent / ".wheelhouse"

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("sync_wheelhouse")


def sync() -> int:
    """Mirror ``gs://{BUCKET}/{PREFIX}`` into ``DEST``; return an exit code."""
    DEST.mkdir(parents=True, exist_ok=True)
    try:
        client = storage.Client()
        blobs = list(client.list_blobs(BUCKET, prefix=PREFIX))
    except Exception:  # noqa: BLE001 — auth/network/bucket failures all degrade the same way
        logger.exception("could not list gs://%s/%s", BUCKET, PREFIX)
        return 1

    downloaded = skipped = 0
    for blob in blobs:
        name = blob.name[len(PREFIX) :] if blob.name.startswith(PREFIX) else blob.name
        if not name:  # the prefix "directory" placeholder object, if any
            continue
        target = DEST / name
        # Skip when a same-size file is already present. Published artifacts are
        # server-side immutable (cannobserv#215), so name + size is sufficient;
        # no need to fetch and compare the crc32c.
        if target.exists() and target.stat().st_size == blob.size:
            skipped += 1
            continue
        blob.download_to_filename(target)
        downloaded += 1

    logger.info(
        "wheelhouse in sync: %d downloaded, %d already present -> %s",
        downloaded,
        skipped,
        DEST,
    )
    return 0


if __name__ == "__main__":
    sys.exit(sync())
