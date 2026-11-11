"""Where Replicator keeps a digest for good: two stores (archiver#276, #380 D4).

A persisted revision's bytes live at ``gs://co-gcs-replicator/blobs/<sha256>.bin``
with no expiry. The persist contract gives the rule: record the digest, never a
URL, and derive the location with co-core's ``blobstore.gcs_uri(bucket,
digest)`` from the configured bucket. A leaf module, because both the persist
issuer and replication issuance need it and each already imports the other's
neighbours.

**Captures have their own bucket** (#380 D4, CannObserv/replicator#189):
``co-gcs-captures`` holds every capture byte, temporary and kept, and never a
raw fetched blob, so Archiver may read it without crossing its ``content.blobs``
boundary. A capture belongs to the store its ``capture_stored.blob_uri`` names:
one in ``co-gcs-captures`` is kept there; the captures stored before the split
(in ``co-gcs-blobs``) were kept with the revisions.
"""

from co_core.pure.util.blobstore import gcs_uri
from sqlalchemy import ColumnElement, or_

# REPLICATOR_PERMANENT_BUCKET on co-replicator: revisions' permanent store.
PERMANENT_BUCKET = "co-gcs-replicator"

# Every capture byte, temporary and kept (#380 D4); no raw blob is ever here.
CAPTURES_BUCKET = "co-gcs-captures"
# Where a kept capture lives inside it, as CannObserv/replicator#189 names it.
CAPTURES_KEPT_PREFIX = "blobs"


def permanent_blob_uri(digest: str) -> str:
    """The permanent store's URI for ``digest``. Raises ``ValueError`` on a malformed one."""
    return gcs_uri(PERMANENT_BUCKET, digest)


def in_captures_store(uri: str | None) -> bool:
    """Whether ``uri`` names an object in the captures bucket (and nowhere else)."""
    return uri is not None and uri.startswith(f"gs://{CAPTURES_BUCKET}/")


def kept_capture_uri(blob_uri: str | None, digest: str) -> str:
    """Where a capture stored at ``blob_uri`` is kept once persisted.

    Raises ``ValueError`` on a malformed digest.
    """
    if in_captures_store(blob_uri):
        return gcs_uri(CAPTURES_BUCKET, digest, CAPTURES_KEPT_PREFIX)
    return permanent_blob_uri(digest)


def stored_in_captures_bucket(column: ColumnElement[str]) -> ColumnElement[bool]:
    """SQL: ``column`` names an object in the captures bucket (``in_captures_store``)."""
    return column.startswith(f"gs://{CAPTURES_BUCKET}/", autoescape=True)


def stored_outside_captures_bucket(column: ColumnElement[str]) -> ColumnElement[bool]:
    """SQL: the complement, a ``NULL`` included: the revisions' store."""
    return or_(column.is_(None), ~stored_in_captures_bucket(column))
