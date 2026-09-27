"""Where Replicator's permanent, content-addressed store keeps a digest (archiver#276).

A persisted revision's bytes live at ``gs://co-gcs-replicator/blobs/<sha256>.bin``
with no expiry. The persist contract gives the rule: record the digest, never a
URL, and derive the location with co-core's ``blobstore.gcs_uri(bucket,
digest)`` from the configured bucket. A leaf module, because both the persist
issuer and replication issuance need it and each already imports the other's
neighbours.
"""

from co_core.pure.util.blobstore import gcs_uri

# REPLICATOR_PERMANENT_BUCKET on co-replicator, production's only permanent store.
PERMANENT_BUCKET = "co-gcs-replicator"


def permanent_blob_uri(digest: str) -> str:
    """The permanent store's URI for ``digest``. Raises ``ValueError`` on a malformed one."""
    return gcs_uri(PERMANENT_BUCKET, digest)
