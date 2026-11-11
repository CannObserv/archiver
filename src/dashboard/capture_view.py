"""The Viewport Capture card's context (archiver#380 slice A).

Pure: the route reads the source's latest ``capture_commands`` row and this
turns it into what ``info_sources/_capture_card.html`` shows. Metadata only:
Archiver reads no stored bytes, so the image itself waits on slice D.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TypedDict

from src.core.models import CaptureCommand
from src.core.services.capture import STATE_REQUESTED
from src.dashboard.watch_panel import format_age

#: How often the card re-reads itself while its command is open.
POLL_SECONDS = 5

#: Where a dead-lettered command lands - Replicator's, probed by broker.
DLQ = "content.capture.dlq"


class CaptureView(TypedDict):
    state: str
    open: bool
    requested_ago: str | None
    captured_ago: str | None
    reason: str | None
    detail: str | None
    status_code: int | None
    image_width: int | None
    image_height: int | None
    size_bytes: int | None
    content_fingerprint: str | None
    final_url: str | None
    blob_uri: str | None
    expires_at: datetime | None
    expired: bool
    persisted_at: datetime | None
    horizon_minutes: int
    dlq: str


def capture_view(
    command: CaptureCommand | None, *, now: datetime, horizon: timedelta
) -> CaptureView | None:
    """``None`` for a source never captured; else the card's fields for ``command``."""
    if command is None:
        return None
    expires = command.blob_expires_at
    if expires is not None and expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    return CaptureView(
        state=command.state,
        open=command.state == STATE_REQUESTED,
        requested_ago=format_age(command.issued_at, now=now),
        captured_ago=format_age(command.captured_at, now=now),
        reason=command.reason,
        detail=command.detail,
        status_code=command.status_code,
        image_width=command.image_width,
        image_height=command.image_height,
        size_bytes=command.size_bytes,
        content_fingerprint=command.content_fingerprint,
        final_url=command.final_url,
        blob_uri=command.blob_uri,
        expires_at=expires,
        expired=expires is not None and expires <= now,
        persisted_at=command.persisted_at,
        horizon_minutes=max(1, int(horizon.total_seconds() // 60)),
        dlq=DLQ,
    )
