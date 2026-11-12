"""Where kept bytes live: the revisions' permanent store, and the captures' own bucket (#380 D4)."""

import pytest

from src.core.replication.permanent_store import (
    CAPTURES_BUCKET,
    PERMANENT_BUCKET,
    in_captures_store,
    kept_capture_uri,
    permanent_blob_uri,
)

DIGEST = "a" * 64


def test_revisions_are_kept_in_replicators_permanent_store():
    assert permanent_blob_uri(DIGEST) == f"gs://{PERMANENT_BUCKET}/blobs/{DIGEST}.bin"


def test_the_captures_bucket():
    assert CAPTURES_BUCKET == "co-gcs-captures"


@pytest.mark.parametrize(
    ("uri", "expected"),
    [
        (f"gs://co-gcs-captures/temp/{DIGEST}.bin", True),
        (f"gs://co-gcs-captures/blobs/{DIGEST}.bin", True),
        (f"gs://co-gcs-blobs/blobs/{DIGEST}.bin", False),
        (f"gs://co-gcs-replicator/blobs/{DIGEST}.bin", False),
        # A bucket whose name merely starts with ours is another bucket.
        (f"gs://co-gcs-captures-old/blobs/{DIGEST}.bin", False),
        ("gs://co-gcs-captures", False),
        (f"file:///var/blobs/{DIGEST}.bin", False),
        (None, False),
    ],
)
def test_a_capture_is_in_the_captures_store_by_its_uri(uri, expected):
    assert in_captures_store(uri) is expected


def test_a_capture_stored_in_its_own_bucket_is_kept_there():
    uri = kept_capture_uri(f"gs://co-gcs-captures/temp/{DIGEST}.bin", DIGEST)
    assert uri == f"gs://co-gcs-captures/blobs/{DIGEST}.bin"


def test_a_capture_stored_before_d4_was_kept_with_the_revisions():
    """The two captures that predate the split live in Replicator's permanent store."""
    uri = kept_capture_uri(f"gs://co-gcs-blobs/blobs/{DIGEST}.bin", DIGEST)
    assert uri == permanent_blob_uri(DIGEST)


def test_a_malformed_digest_raises():
    with pytest.raises(ValueError):
        kept_capture_uri(f"gs://co-gcs-captures/temp/{DIGEST}.bin", "not-a-digest")
