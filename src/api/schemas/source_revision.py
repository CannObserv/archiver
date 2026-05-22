"""Pydantic schemas for SourceRevision create / read / patch."""

import re
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

_FP_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


class SourceRevisionCreate(BaseModel):
    """Request body for POST /source-revisions.

    ``source_revision_id`` is optional and may be supplied by the client
    (e.g. Watcher) so the scratch file at ``content_cache_uri`` can be
    written under its final filename BEFORE the POST round-trips. When
    omitted, the server allocates a ULID. Idempotency on
    ``(info_source_id, content_fingerprint)`` still wins on re-POST —
    a client-supplied ULID is honored on fresh inserts only; existing
    rows are returned as-is.
    """

    info_source_id: str
    content_fingerprint: str
    captured_at: datetime
    source_revision_id: str | None = None
    content_size_bytes: int | None = None
    content_media_type: str | None = None
    content_cache_uri: str | None = None
    content_cache_expires_at: datetime | None = None

    @field_validator("content_fingerprint")
    @classmethod
    def _fingerprint_format(cls, v: str) -> str:
        """Require sha256:<64 lowercase hex>."""
        if not _FP_PATTERN.match(v):
            raise ValueError("must match 'sha256:<64 lowercase hex>'")
        return v


class SourceRevisionOut(BaseModel):
    """Response body for source-revision endpoints."""

    source_revision_id: str = Field(description="ULID identifying this SourceRevision.")
    info_source_id: str = Field(
        description="ULID of the InfoSource this revision was captured from."
    )
    content_fingerprint: str = Field(
        description=(
            "Content hash in 'sha256:<64 hex chars>' format. "
            "Together with info_source_id, forms the idempotency key."
        )
    )
    captured_at: datetime = Field(
        description="UTC timestamp when the content was fetched and this revision recorded."
    )
    content_size_bytes: int | None = Field(
        description="Size of the fetched content in bytes, if recorded."
    )
    content_media_type: str | None = Field(
        description="MIME type of the fetched content (e.g. 'text/html'), if recorded."
    )
    content_cache_uri: str | None = Field(
        description=(
            "Watcher's scratch-file URI for the cached fetch (e.g. a file:// path). "
            "Null after cache expiry or explicit clearance."
        )
    )
    content_cache_expires_at: datetime | None = Field(
        description="UTC timestamp after which the cached content at content_cache_uri expires."
    )


class SourceRevisionCachePatch(BaseModel):
    """Request body for PATCH /source-revisions/{id}.

    Both fields are optional (omitting leaves the DB column untouched).
    Supplying ``null`` explicitly clears the field.
    Use ``model_dump(exclude_unset=True)`` to distinguish omitted from null.
    """

    model_config = {"extra": "forbid"}

    content_cache_uri: str | None = None
    content_cache_expires_at: datetime | None = None
