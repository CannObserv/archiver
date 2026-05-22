"""Pydantic IO schemas for InfoItem endpoints."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from src.core.models import FragmentRole


class RepSpecAssignmentCreate(BaseModel):
    """One rep_spec assignment to atomically attach to a new InfoItem."""

    rep_spec_id: str = Field(min_length=1)
    activated_at: datetime | None = Field(default=None)


# ---------------------------------------------------------------------------
# Sub-resource create bodies (used by assignment routes)
# ---------------------------------------------------------------------------


class InfoItemSourceCreate(BaseModel):
    """Request body for POST /info-items/{id}/info-sources."""

    info_source_id: str = Field(min_length=1, description="ULID of an existing InfoSource.")
    role: FragmentRole | None = Field(
        default=None,
        description=(
            "Binding role. ``null`` (default) for root-shaped InfoSources (the "
            "InfoItem's primary). ``'cross_check'`` or ``'sub_aspect'`` for "
            "fragment-shaped InfoSources sharing the primary's root."
        ),
    )


class InfoItemRepSpecCreate(BaseModel):
    """Request body for POST /info-items/{id}/rep-spec-assignments."""

    rep_spec_id: str = Field(min_length=1, description="ULID of an existing RepSpec.")
    activated_at: datetime | None = Field(
        default=None, description="Effective date; defaults to now() when omitted."
    )


class InfoItemRepSpecPublicUrlPatch(BaseModel):
    """Request body for PATCH /info-items/{id}/rep-spec-assignments/{assignment_id}.

    Writes the provider-native public URL back to an assignment row (active or
    deactivated). Called by Replicator after a successful replication job.
    """

    model_config = {"extra": "forbid"}
    public_url: str = Field(
        min_length=1,
        description="Provider-native public URL of the replicated artefact.",
    )


class InfoItemSourceRevisionCreate(BaseModel):
    """Request body for POST /info-items/{id}/source-revisions."""

    source_revision_id: str = Field(min_length=1, description="ULID of an existing SourceRevision.")
    bound_at: datetime | None = Field(
        default=None, description="Bind timestamp; defaults to now() when omitted."
    )


class InfoItemCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    owner: str | None = Field(default=None, max_length=200)
    rep_fields: dict[str, Any] = Field(default_factory=dict)
    initial_source_spec: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Optional SourceSpec document to atomically create alongside the new "
            "InfoItem as the primary (NULL-role) binding. Validated before any row "
            "is written; on validation failure neither InfoItem nor InfoSource is "
            "persisted."
        ),
    )
    initial_rep_spec_assignments: list[RepSpecAssignmentCreate] = Field(
        default_factory=list,
        description=(
            "Optional list of RepSpec assignments to atomically create alongside "
            "the new InfoItem. Each rep_spec_id must reference an existing RepSpec. "
            "rep_fields are validated against each RepSpec's required_fields."
        ),
    )


class InfoItemSourceOut(BaseModel):
    """Light projection of an info_item_sources row."""

    info_source_id: str
    role: str | None
    created_at: datetime


class InfoItemRepSpecOut(BaseModel):
    """Projection of an info_item_rep_specs row."""

    id: str
    rep_spec_id: str
    activated_at: datetime
    deactivated_at: datetime | None
    public_url: str | None


class InfoItemSourceRevisionOut(BaseModel):
    """Projection of an info_item_source_revisions row."""

    info_item_id: str
    source_revision_id: str
    bound_at: datetime


class InfoItemOut(BaseModel):
    info_item_id: str = Field(description="ULID identifying this InfoItem.")
    name: str = Field(description="Human-readable label for the InfoItem.")
    description: str | None = Field(
        description="Optional freetext description of the InfoItem's content or purpose."
    )
    owner: str | None = Field(
        description="Optional owner identifier (team or individual) for this InfoItem."
    )
    rep_fields: dict[str, Any] = Field(
        description="Operator-defined JSONB bag of structured metadata fields for this item."
    )
    created_at: datetime = Field(description="UTC timestamp when the InfoItem was created.")
    updated_at: datetime = Field(description="UTC timestamp of the last update to the InfoItem.")
    info_item_sources: list[InfoItemSourceOut] = Field(
        default_factory=list,
        description=(
            "Bound InfoSources (primary + fragments). Exactly one active row has role null "
            "(primary); others carry 'cross_check' or 'sub_aspect'."
        ),
    )
    info_item_rep_specs: list[InfoItemRepSpecOut] = Field(
        default_factory=list,
        description="Effective-dated RepSpec assignments for this InfoItem.",
    )
    dashboard_url: str | None = Field(
        default=None,
        description=(
            "Absolute URL of this item's Archiver dashboard detail page. "
            "Null when ARCHIVER_PUBLIC_BASE_URL is not configured on the server."
        ),
    )
