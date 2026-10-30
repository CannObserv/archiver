"""Builders for the composer's inputs: co-core's watch events and an ``ItemFacts``."""

from datetime import UTC, datetime

from co_core.pure.models.changes import (
    ChangeDetectedEvent,
    WatchErrorEvent,
    WatchRecoveredEvent,
)

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
