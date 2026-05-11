"""Pydantic IO schemas for top-level /rep-specs endpoints.

RepSpecs are immutable post-create: the API exposes POST/GET only, no
PATCH/DELETE. Operators reassign a new RepSpec to evolve provider config.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class RepSpecCreate(BaseModel):
    """Request body for POST /rep-specs.

    ``schema_version`` is server-defaulted to 1 — only v1 exists today, so
    accepting a client-supplied value would be ceremony. Bump the server
    default (and add a discriminator) once a v2 envelope ships.
    """

    model_config = {"extra": "forbid"}

    provider: str = Field(
        min_length=1,
        max_length=50,
        description="Provider key (e.g. 'gcs', 'gdrive', 'ia'). Validated via validate_rep_spec.",
    )
    name: str = Field(
        min_length=1,
        max_length=200,
        description="Operator-friendly label for this RepSpec. Not unique by design.",
    )
    document: dict[str, Any] = Field(
        description=(
            "RepSpec envelope document. Validated against rep_spec_schema/v1.json + "
            "the per-provider sub-schema at rep_spec_schema/providers/{provider}/v1.json."
        ),
    )


class RepSpecOut(BaseModel):
    """Projection of a rep_specs row."""

    rep_spec_id: str
    provider: str
    name: str
    schema_version: int
    document: dict[str, Any]
    created_at: datetime
