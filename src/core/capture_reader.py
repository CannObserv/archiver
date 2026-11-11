"""Reading a capture's image from the captures bucket (archiver#380 slice D, D4).

The dashboard shows a viewport capture by reading its PNG and serving it behind
the dashboard's login (``GET /dashboard/info-sources/{id}/captures/{command_id}.png``).
The processor-text reader's guards (``src.core.notifications.diff_loader``), for
images:

- **The captures bucket only** (``permanent_store.CAPTURES_BUCKET``). It holds
  every capture byte and never a raw fetched blob (CannObserv/replicator#189).
  Archiver's ``content.blobs`` boundary is unqualified, so its identity can't
  read the other buckets, and this code won't ask: a URI anywhere else is
  unavailable without a request.
- **Capped** (``ARCHIVER_CAPTURE_MAX_IMAGE_BYTES``, default 64 MiB): the object's
  ``size`` is checked first and the download is ranged, so a wrong size can't
  overrun the cap.
- **Hash-checked** against the capture's ``content_fingerprint`` (bare hex), so
  the bytes served are the bytes Replicator reported.
- **Off the loop**: the SDK is synchronous; ``read_capture`` runs it in a thread.

**The identity** is a unit credential, ``capture-reader`` (``LoadCredential=``
with an empty ``SetCredential=`` fallback), a service account holding
``objectViewer`` on the captures bucket alone. The client is built from that
key explicitly, never ``GOOGLE_APPLICATION_CREDENTIALS``. No credential file at
all is dormant (a dev server, the suite, a unit that does not load it); an
empty or unusable one is a WARNING, because the unit meant to read and can't.
Either way the card shows metadata only: degrade, don't refuse.
"""

import asyncio
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from co_core.pure.util.hashing import sha256
from google.api_core.exceptions import NotFound
from google.cloud import storage
from google.oauth2 import service_account

from src.core.logging import get_logger
from src.core.replication.permanent_store import CAPTURES_BUCKET, in_captures_store

logger = get_logger(__name__)

MAX_IMAGE_BYTES_ENV = "ARCHIVER_CAPTURE_MAX_IMAGE_BYTES"
DEFAULT_MAX_IMAGE_BYTES = 64 * 1024 * 1024
#: The ``LoadCredential=`` name ``deploy/archiver.service`` gives the key.
CREDENTIAL_NAME = "capture-reader"
#: Where the unit loads it from.
CREDENTIAL_FILE = "/etc/archiver/capture-reader.json"
#: Seconds for one metadata read or one download.
TIMEOUT_SECONDS = 30.0


class CaptureUnavailable(Exception):
    """A capture image that can't be served, with the reason."""


@dataclass
class CaptureReader:
    """One process's read access to the captures bucket. Built by the lifespan, closed by it."""

    client: Any  # google.cloud.storage.Client
    max_image_bytes: int = DEFAULT_MAX_IMAGE_BYTES

    def __repr__(self) -> str:
        return f"CaptureReader(bucket={CAPTURES_BUCKET!r}, max_image_bytes={self.max_image_bytes})"

    def read(self, uri: str, digest: str) -> bytes:
        """One image: bucket-checked, size-checked, read, hash-checked. Blocking."""
        name = uri.removeprefix(f"gs://{CAPTURES_BUCKET}/")
        if not in_captures_store(uri) or not name:
            raise CaptureUnavailable("not in the captures bucket")
        try:
            blob = self.client.bucket(CAPTURES_BUCKET).get_blob(name, timeout=TIMEOUT_SECONDS)
            if blob is not None and blob.size is not None and blob.size > self.max_image_bytes:
                raise CaptureUnavailable("image too large")
            data = (
                blob.download_as_bytes(
                    end=self.max_image_bytes, checksum=None, timeout=TIMEOUT_SECONDS
                )
                if blob is not None
                else None
            )
        except CaptureUnavailable:
            raise
        except NotFound:
            data = None
        except Exception as e:  # google.auth and google.api_core raise their own trees
            logger.warning(
                "capture image unreadable", extra={"uri": uri, "error_type": type(e).__name__}
            )
            raise CaptureUnavailable("image unreadable") from e
        if data is None:
            logger.info("capture image not found", extra={"uri": uri})
            raise CaptureUnavailable("image not found")
        if len(data) > self.max_image_bytes:
            raise CaptureUnavailable("image too large")
        if sha256(data) != digest:
            logger.warning("capture image failed its hash check", extra={"uri": uri})
            raise CaptureUnavailable("image failed its hash check")
        return data

    def close(self) -> None:
        self.client.close()


def _storage_client(*, info: dict[str, Any]) -> Any:
    """A client authenticated as the key's service account and nothing else."""
    credentials = service_account.Credentials.from_service_account_info(info)
    return storage.Client(project=info.get("project_id"), credentials=credentials)


def _max_image_bytes(environ: Mapping[str, str]) -> int:
    raw = environ.get(MAX_IMAGE_BYTES_ENV, "").strip()
    if raw.isdigit() and int(raw) > 0:
        return int(raw)
    if raw:
        logger.warning(
            "%s is not a positive integer; keeping %d", MAX_IMAGE_BYTES_ENV, DEFAULT_MAX_IMAGE_BYTES
        )
    return DEFAULT_MAX_IMAGE_BYTES


def _credential_path(environ: Mapping[str, str]) -> Path | None:
    directory = environ.get("CREDENTIALS_DIRECTORY", "").strip()
    return Path(directory) / CREDENTIAL_NAME if directory else None


def capture_reader_from_environ(
    environ: Mapping[str, str] = os.environ,
) -> tuple[CaptureReader | None, str | None]:
    """The reader, or ``None`` and why. Never raises; the why never quotes the key.

    Builds a client but makes no request: an outage must not stop a start.
    """
    path = _credential_path(environ)
    if path is None or not path.exists():
        return None, f"no {CREDENTIAL_NAME} credential"
    try:
        raw = path.read_text().strip()
    except (OSError, ValueError):
        raw = ""
    if not raw:
        return None, f"empty {CREDENTIAL_NAME} credential"
    try:
        client = _storage_client(info=json.loads(raw))
    except Exception as e:
        return None, f"unusable {CREDENTIAL_NAME} credential ({type(e).__name__})"
    return CaptureReader(client, max_image_bytes=_max_image_bytes(environ)), None


def announced_capture_reader(environ: Mapping[str, str] = os.environ) -> CaptureReader | None:
    """The process's reader, or ``None``, saying which once: the lifespan's call.

    A credential the unit loads but can't use is a WARNING (it meant to read);
    no credential at all is the dormant INFO.
    """
    reader, reason = capture_reader_from_environ(environ)
    if reader is not None:
        logger.info("capture image reader configured (bucket %s)", CAPTURES_BUCKET)
    elif reason == f"no {CREDENTIAL_NAME} credential":
        logger.info("capture image reader not configured: %s", reason)
    else:
        logger.warning(
            "capture image reader not configured: %s; captures show metadata only", reason
        )
    return reader


async def read_capture(reader: CaptureReader, uri: str, digest: str) -> bytes:
    """The image's bytes, read off the loop. Raises :class:`CaptureUnavailable`."""
    return await asyncio.to_thread(reader.read, uri, digest)
