"""Pydantic IO schemas for top-level InfoSource endpoints."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class InfoSourceCreate(BaseModel):
    """Request body for POST /info-sources."""

    model_config = {"extra": "forbid"}

    url: str = Field(description="URL to fetch. Immutable after creation.")
    source_specs: list[dict[str, Any]] = Field(
        description=(
            "Ordered list of extraction specs. First element is the primary strategy; "
            "subsequent elements are cross-check alternatives. All must share a "
            "content-kind family (html_text or json). Each element is a SourceSpec v1 "
            "document (schema_version, extraction, fingerprint — no target section)."
        )
    )


class InfoSourcePatch(BaseModel):
    """Request body for PATCH /info-sources/{id}/source-specs."""

    model_config = {"extra": "forbid"}

    source_specs: list[dict[str, Any]] = Field(
        description="Replacement source_specs list. Same constraints as on creation."
    )


class InfoSourceOut(BaseModel):
    """Projection of an info_sources row."""

    info_source_id: str = Field(description="ULID identifying this InfoSource.")
    url: str = Field(description="URL to fetch.")
    source_specs: list[dict[str, Any]] = Field(description="Ordered list of extraction specs.")
    created_at: datetime = Field(description="UTC timestamp when the InfoSource was created.")
