"""Typed Pydantic models for change-bus event payloads."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class SourceRevisionCapturedEvent(BaseModel):
    """Event emitted when a new SourceRevision is recorded for an InfoSource.

    Producer: Archiver (POST /source-revisions on insert; not on idempotent no-op).
    Subscribers: Replicator, Notifier, etc.
    """

    model_config = ConfigDict(extra="forbid")

    event_type: Literal["source_revision_captured"] = "source_revision_captured"
    occurred_at: datetime
    info_source_id: str
    source_revision_id: str
    content_fingerprint: str
    info_item_ids: list[str]
