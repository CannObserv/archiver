"""Builders for the composer's inputs (co-core events, an ``ItemFacts``) and a fake bucket."""

from datetime import UTC, datetime

from co_core.pure.models.changes import (
    ChangeDetectedEvent,
    WatchErrorEvent,
    WatchRecoveredEvent,
)
from co_core.pure.util.hashing import prefixed_sha256, sha256

from src.core.notifications.content import ItemFacts

OCCURRED_AT = datetime(2026, 4, 14, 12, 0, 0, tzinfo=UTC)
ITEM_ID = "01HV0000000000000000000001"
SOURCE_ID = "01HV0000000000000000000002"
EVENT_ID = "01HV0000000000000000000003"
PREVIOUS_FP = "sha256:" + "a" * 64
CURRENT_FP = "sha256:" + "b" * 64

ITEM = ItemFacts(name="Test Item", url="https://example.com")


def make_event(event_type: str = "change_detected", **fields):
    """One of the three events, with the common fields filled in."""
    common = {
        "occurred_at": OCCURRED_AT,
        "event_id": EVENT_ID,
        "info_item_id": ITEM_ID,
        "info_source_id": SOURCE_ID,
    }
    if event_type == "change_detected":
        defaults = {
            "previous_fingerprint": PREVIOUS_FP,
            "current_fingerprint": CURRENT_FP,
            "previous_text_uri": f"gs://co-gcs-processor/blobs/{'a' * 64}.bin",
            "current_text_uri": f"gs://co-gcs-processor/blobs/{'b' * 64}.bin",
        }
        return ChangeDetectedEvent(**common | defaults | fields)
    if event_type == "watch_error":
        return WatchErrorEvent(**common | {"reason": "http_status"} | fields)
    if event_type == "watch_recovered":
        return WatchRecoveredEvent(**common | {"error_since": None} | fields)
    raise ValueError(event_type)


def uri(text: bytes, bucket: str = "co-gcs-processor") -> str:
    """Where the processor stores ``text``: content-addressed."""
    return f"gs://{bucket}/blobs/{prefixed_sha256(sha256(text)).removeprefix('sha256:')}.bin"


class FakeBlob:
    def __init__(self, data: bytes, size: int | None = None):
        self.data = data
        self.size = len(data) if size is None else size
        self.downloads: list[dict] = []

    def download_as_bytes(self, **kwargs) -> bytes:
        self.downloads.append(kwargs)
        end = kwargs.get("end")
        return self.data if end is None else self.data[: end + 1]


class FakeBucket:
    def __init__(self, store: "FakeStorage", name: str):
        self.store, self.name = store, name

    def get_blob(self, name: str, **kwargs):
        self.store.gets.append((self.name, name))
        if self.store.error is not None:
            raise self.store.error
        return self.store.objects.get((self.name, name))


class FakeStorage:
    """Duck-types the slice of ``google.cloud.storage.Client`` the reader uses."""

    def __init__(self, *texts: bytes, bucket: str = "co-gcs-processor"):
        self.objects = {
            (bucket, u.removeprefix(f"gs://{bucket}/")): FakeBlob(t)
            for t in texts
            for u in [uri(t, bucket)]
        }
        self.gets: list[tuple[str, str]] = []
        self.error: Exception | None = None
        self.closed = False

    def bucket(self, name: str) -> FakeBucket:
        return FakeBucket(self, name)

    def close(self) -> None:
        self.closed = True
