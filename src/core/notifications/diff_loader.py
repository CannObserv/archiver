"""Loading a change's diff (archiver#367, D4): read both texts back from the processor bucket.

Ported from Watcher ``3ba20be`` ``src/core/notifications/diff_loader.py``. Watcher
found each text through its own ``process_commands`` table; Archiver gets the
URI on the event (``ChangeDetectedEvent.previous_text_uri``/``current_text_uri``),
so none of that ports. Its guards do:

- **The processor bucket only** (``ARCHIVER_PROCESSOR_TEXT_BUCKET``, set by
  ``archiver.service`` alone). A URI naming another bucket or scheme is
  unavailable without a read. Archiver's ``content.blobs`` boundary is
  unqualified, so the identity can't read raw blobs, and this code won't ask.
- **Capped** (``ARCHIVER_DIFF_MAX_INPUT_BYTES``, default 1 MiB). The object's
  ``size`` is checked before downloading, and the download itself is ranged, so
  a wrong size can't overrun the cap.
- **Hash-checked** against the fingerprint, which is the text's digest
  (co-core's ``ChangeDetectedEvent``: there is no separate ``*_text_sha256``).
- **Off the loop**: the SDK is synchronous, so reads and ``difflib`` run in a thread.
- **Never raises.** A failure is ``ChangeDiff(unavailable=<reason>)`` and the
  notification still goes. A 404 (a lifecycle rule may reap old text; unmeasured)
  is INFO, not a retry and not an ERROR.

**The identity** is a unit credential, ``processor-text-reader``
(``LoadCredential=`` with an empty ``SetCredential=`` fallback), and the client
is built from that key explicitly. Never ``GOOGLE_APPLICATION_CREDENTIALS``,
which would make it ambient for every GCS call the process makes. A missing key
leaves every diff unavailable: degrade, don't refuse.
"""

import asyncio
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from co_core.pure.models.changes import ChangeDetectedEvent
from co_core.pure.util.hashing import prefixed_sha256, sha256
from google.api_core.exceptions import NotFound
from google.cloud import storage
from google.oauth2 import service_account

from src.core.logging import get_logger
from src.core.notifications.diff import ChangeDiff, compute_change_diff

logger = get_logger(__name__)

BUCKET_ENV = "ARCHIVER_PROCESSOR_TEXT_BUCKET"
MAX_INPUT_BYTES_ENV = "ARCHIVER_DIFF_MAX_INPUT_BYTES"
DEFAULT_MAX_INPUT_BYTES = 1024 * 1024
#: The ``LoadCredential=`` name ``deploy/archiver.service`` gives the key.
CREDENTIAL_NAME = "processor-text-reader"
#: Where the unit loads it from (docs/NOTIFICATIONS.md).
CREDENTIAL_FILE = "/etc/archiver/processor-text-reader.json"
#: Seconds for one metadata read or one download.
TIMEOUT_SECONDS = 10.0


class _Unavailable(Exception):
    """A text that can't be used, with the reason a reader is shown."""


@dataclass
class TextReader:
    """One process's read access to the processor bucket. Built by the lifespan, closed by it."""

    client: Any  # google.cloud.storage.Client
    bucket: str
    max_input_bytes: int = DEFAULT_MAX_INPUT_BYTES

    def __repr__(self) -> str:
        return f"TextReader(bucket={self.bucket!r}, max_input_bytes={self.max_input_bytes})"

    def read(self, uri: str, fingerprint: str, label: str) -> bytes:
        """One text: bucket-checked, size-checked, read, hash-checked. Blocking."""
        prefix = f"gs://{self.bucket}/"
        name = uri.removeprefix(prefix)
        if not uri.startswith(prefix) or not name:
            raise _Unavailable(f"{label} not in the processor bucket")
        try:
            blob = self.client.bucket(self.bucket).get_blob(name, timeout=TIMEOUT_SECONDS)
            if blob is not None and blob.size is not None and blob.size > self.max_input_bytes:
                raise _Unavailable("content too large")
            text = (
                blob.download_as_bytes(
                    end=self.max_input_bytes, checksum=None, timeout=TIMEOUT_SECONDS
                )
                if blob is not None
                else None
            )
        except _Unavailable:
            raise
        except NotFound:
            text = None
        except Exception as e:  # google.auth and google.api_core raise their own trees
            logger.warning(
                "processor text unreadable: no diff",
                extra={"uri": uri, "error_type": type(e).__name__},
            )
            raise _Unavailable(f"{label} unreadable") from e
        if text is None:
            logger.info("processor text not found: no diff", extra={"uri": uri})
            raise _Unavailable(f"{label} unreadable")
        if len(text) > self.max_input_bytes:
            raise _Unavailable("content too large")
        if prefixed_sha256(sha256(text)) != fingerprint:
            logger.warning("processor text failed its hash check: no diff", extra={"uri": uri})
            raise _Unavailable(f"{label} failed its hash check")
        return text

    def close(self) -> None:
        self.client.close()


def _storage_client(*, info: dict[str, Any]) -> Any:
    """A client authenticated as the key's service account and nothing else."""
    credentials = service_account.Credentials.from_service_account_info(info)
    return storage.Client(project=info.get("project_id"), credentials=credentials)


def _max_input_bytes(environ: Mapping[str, str]) -> int:
    raw = environ.get(MAX_INPUT_BYTES_ENV, "").strip()
    if raw.isdigit() and int(raw) > 0:
        return int(raw)
    if raw:
        logger.warning(
            "%s is not a positive integer; keeping %d", MAX_INPUT_BYTES_ENV, DEFAULT_MAX_INPUT_BYTES
        )
    return DEFAULT_MAX_INPUT_BYTES


def text_reader_from_environ(
    environ: Mapping[str, str] = os.environ,
) -> tuple[TextReader | None, str | None]:
    """The reader, or ``None`` and why. Never raises; the why never quotes the key.

    Builds a client but makes no request: an outage must not stop a start.
    """
    bucket = environ.get(BUCKET_ENV, "").strip()
    if not bucket:
        return None, f"{BUCKET_ENV} unset"
    directory = environ.get("CREDENTIALS_DIRECTORY", "").strip()
    try:
        raw = (Path(directory) / CREDENTIAL_NAME).read_text().strip() if directory else ""
    except (OSError, ValueError):
        raw = ""
    if not raw:
        return None, f"no {CREDENTIAL_NAME} credential"
    try:
        client = _storage_client(info=json.loads(raw))
    except Exception as e:
        return None, f"unusable {CREDENTIAL_NAME} credential ({type(e).__name__})"
    return TextReader(client, bucket, max_input_bytes=_max_input_bytes(environ)), None


def announced_text_reader(environ: Mapping[str, str] = os.environ) -> TextReader | None:
    """The process's reader, or ``None``, saying which once: the lifespan's call.

    A bucket without a usable key is a WARNING: the unit meant to read and can't,
    so every change diff is unavailable. No bucket at all (a dev server, the
    suite) is the dormant INFO.
    """
    reader, reason = text_reader_from_environ(environ)
    if reader is not None:
        logger.info("processor text reader configured (bucket %s)", reader.bucket)
    elif environ.get(BUCKET_ENV, "").strip():
        logger.warning(
            "processor text reader not configured: %s; change diffs are unavailable", reason
        )
    else:
        logger.info("processor text reader not configured: %s", reason)
    return reader


async def read_stored_text(
    reader: TextReader, uri: str, fingerprint: str
) -> tuple[bytes | None, str | None]:
    """``(text, None)``, or ``(None, reason)``. The D4 proof CLI's one read."""
    try:
        return await asyncio.to_thread(reader.read, uri, fingerprint, "text"), None
    except _Unavailable as e:
        return None, str(e)


async def load_change_diff(reader: TextReader | None, event: ChangeDetectedEvent) -> ChangeDiff:
    """The diff for one change; never raises. ``reader=None`` makes it unavailable."""
    log_extra = {"info_item_id": event.info_item_id, "event_id": event.event_id}
    try:
        if event.previous_text_uri is None:
            raise _Unavailable("previous text not stored")
        if reader is None:
            raise _Unavailable("previous text unreadable")
        previous = await asyncio.to_thread(
            reader.read, event.previous_text_uri, event.previous_fingerprint, "previous text"
        )
        current = await asyncio.to_thread(
            reader.read, event.current_text_uri, event.current_fingerprint, "current text"
        )
        diff = await asyncio.to_thread(compute_change_diff, previous, current)
        if not diff.hunks:
            # The fingerprints differ, so the bytes do; the word split collapsed
            # the whitespace the difference lived in (Watcher CR 11).
            raise _Unavailable("whitespace-only change")
    except _Unavailable as e:
        logger.info("change diff unavailable", extra={**log_extra, "reason": str(e)})
        return ChangeDiff(unavailable=str(e))
    except Exception as e:
        logger.warning(
            "change diff failed: sending without it",
            extra={**log_extra, "error_type": type(e).__name__},
        )
        return ChangeDiff(unavailable="error")
    return diff
