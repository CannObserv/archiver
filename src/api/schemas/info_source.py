"""Pydantic IO schemas for top-level InfoSource endpoints."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from src.core.capture_policy import CapturePolicy

_CAPTURE_POLICY_DOC = (
    "What a viewport capture of this source sends (viewport, full_page, wait) and whether "
    "each new revision triggers one (on_revision). null = no policy: an on-demand capture "
    "uses 1280x800, full page, no wait, and no revision triggers one (archiver#380)."
)


class InfoSourceCreate(BaseModel):
    """Request body for POST /info-sources."""

    model_config = {"extra": "forbid"}

    url: str = Field(description="URL to fetch. Immutable after creation.")
    source_specs: list[dict[str, Any]] = Field(
        description=(
            "Ordered list of extraction specs. First element is the primary strategy; "
            "subsequent elements are fallbacks, tried in order; the first spec whose "
            "extraction is non-empty wins. spec_position > 0 means a fallback was used, "
            "the selector-rot signal. All must share a "
            "content-kind family (html_text: css, xpath; json: jsonpath); full_page "
            "pairs with either. Each element is a SourceSpec v1 "
            "document (schema_version, extraction, fingerprint — no target section)."
        )
    )


class InfoSourcePatch(BaseModel):
    """Request body for PATCH /info-sources/{id}/source-specs."""

    model_config = {"extra": "forbid"}

    source_specs: list[dict[str, Any]] = Field(
        description="Replacement source_specs list. Same constraints as on creation."
    )


class InfoSourceCapturePolicyPatch(BaseModel):
    """Request body for PATCH /info-sources/{id}/capture-policy."""

    model_config = {"extra": "forbid"}

    capture_policy: CapturePolicy | None = Field(
        description=(
            "The replacement policy, replaced whole; omitted keys take their defaults. "
            "null clears it. Each viewport side 1..4096; a delay wait at most 30 s."
        )
    )


class InfoSourceOut(BaseModel):
    """Projection of an info_sources row."""

    info_source_id: str = Field(description="ULID identifying this InfoSource.")
    url: str = Field(description="URL to fetch.")
    source_specs: list[dict[str, Any]] = Field(description="Ordered list of extraction specs.")
    domain_name: str | None = Field(
        description="Hostname derived from URL; references the domains table."
    )
    created_at: datetime = Field(description="UTC timestamp when the InfoSource was created.")
    capture_policy: CapturePolicy | None = Field(default=None, description=_CAPTURE_POLICY_DOC)
