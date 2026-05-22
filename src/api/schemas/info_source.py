"""Pydantic IO schemas for top-level InfoSource endpoints."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class InfoSourceCreate(BaseModel):
    """Request body for POST /info-sources.

    A root source is created when ``parent_info_source_id`` is omitted; the
    ``source_spec`` must then carry ``target.url``. A fragment is created when
    ``parent_info_source_id`` is supplied; the ``source_spec`` must NOT carry
    ``target.url`` — fragments inherit URL/fetch semantics from the parent.

    ``schema_version`` is read from the embedded source_spec document; clients
    must not supply it separately.
    """

    model_config = {"extra": "forbid"}

    source_spec: dict[str, Any] = Field(
        description="A SourceSpec v1 document. Validated against the v1 JSON Schema."
    )
    parent_info_source_id: str | None = Field(
        default=None,
        description=(
            "ULID of an existing root InfoSource. Required for fragment creation; "
            "omit for root creation."
        ),
    )


class InfoSourceOut(BaseModel):
    """Projection of an info_sources row."""

    info_source_id: str = Field(description="ULID identifying this InfoSource.")
    parent_info_source_id: str | None = Field(
        description=("ULID of the root InfoSource this is a fragment of. Null for root sources.")
    )
    source_spec: dict[str, Any] = Field(
        description="SourceSpec v1 document describing how to fetch and extract content."
    )
    schema_version: int = Field(
        description="SourceSpec schema version embedded in the document; always 1 currently."
    )
    url: str | None = Field(
        description=(
            "Canonical URL for root sources. Null for fragment sources (URL inherited from parent)."
        )
    )
    created_at: datetime = Field(description="UTC timestamp when the InfoSource was created.")
