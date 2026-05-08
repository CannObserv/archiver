"""Pydantic schemas for SourceRevision create / read / patch."""

import re
from datetime import datetime

from pydantic import BaseModel, field_validator

_FP_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


class SourceRevisionCreate(BaseModel):
    """Request body for POST /source-revisions."""

    info_source_id: str
    content_fingerprint: str
    captured_at: datetime
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

    source_revision_id: str
    info_source_id: str
    content_fingerprint: str
    captured_at: datetime
    content_size_bytes: int | None
    content_media_type: str | None
    content_cache_uri: str | None
    content_cache_expires_at: datetime | None


class SourceRevisionCachePatch(BaseModel):
    """Request body for PATCH /source-revisions/{id}.

    Both fields are optional (omitting leaves the DB column untouched).
    Supplying ``null`` explicitly clears the field.
    Use ``model_dump(exclude_unset=True)`` to distinguish omitted from null.
    """

    model_config = {"extra": "forbid"}

    content_cache_uri: str | None = None
    content_cache_expires_at: datetime | None = None
