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

    info_source_id: str
    parent_info_source_id: str | None
    source_spec: dict[str, Any]
    schema_version: int
    url: str | None
    created_at: datetime
