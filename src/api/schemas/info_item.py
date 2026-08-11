"""Pydantic IO schemas for InfoItem endpoints."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator


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


class InfoItemWatchSpecPut(BaseModel):
    """Request body for PUT /info-items/{id}/watch-spec.

    Replaces the whole document — this is not a merge. Omitting ``interval`` is
    how "the consumer applies its own default" is expressed, so a merge would
    make that state unreachable once an interval had been set.

    Carries cadence only. Pause state has its own route (``PUT /watch-active``)
    precisely so this body keeps one absence rule instead of two.
    """

    model_config = {"extra": "forbid"}
    document: dict[str, Any] = Field(
        description="A WatchSpec v1 document, validated server-side before it is stored."
    )


class InfoItemWatchActivePut(BaseModel):
    """Request body for PUT /info-items/{id}/watch-active.

    ``active`` is required: NULL on the column means "the registry has no
    opinion yet", which is reachable only by never having written, never by an
    operator asserting it.
    """

    model_config = {"extra": "forbid"}
    active: bool = Field(
        description=(
            "True schedules the item; False is registered-but-paused (keep the item, "
            "stop scheduling). Distinct from removal, which is a deletion."
        )
    )


class InfoItemCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    owner: str | None = Field(default=None, max_length=200)
    rep_fields: dict[str, Any] = Field(default_factory=dict)
    initial_url: str | None = Field(
        default=None,
        description="Optional URL to atomically create an InfoSource binding for this item.",
    )
    initial_source_specs: list[dict[str, Any]] | None = Field(
        default=None,
        description=(
            "Extraction specs for the initial InfoSource. Required when initial_url is set. "
            "Each element is a SourceSpec v1 document (schema_version, extraction, fingerprint)."
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

    @model_validator(mode="after")
    def _check_specs_require_url(self) -> "InfoItemCreate":
        if self.initial_source_specs is not None and self.initial_url is None:
            raise ValueError("initial_source_specs requires initial_url to be set")
        if self.initial_url is not None and self.initial_source_specs is None:
            raise ValueError("initial_url requires initial_source_specs to be set")
        return self


class InfoItemSourceOut(BaseModel):
    """Light projection of an info_item_sources row."""

    info_source_id: str
    is_active: bool = Field(
        description="True when deactivated_at is null (binding is currently active)."
    )
    created_at: datetime
    deactivated_at: datetime | None = Field(
        default=None,
        description="UTC timestamp when this binding was deactivated, or null if still active.",
    )


class InfoItemRepSpecOut(BaseModel):
    """Projection of an info_item_rep_specs row."""

    id: str
    rep_spec_id: str
    activated_at: datetime
    deactivated_at: datetime | None
    public_url: str | None


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
    watch_spec: dict[str, Any] = Field(
        description=(
            "Cadence policy for this item (WatchSpec v1): "
            '\'{"schema_version": 1, "interval": "1d"}\'. `interval` is optional — '
            "when absent the consumer applies its own default, which may be a per-domain "
            "one rather than a global constant. Carries no pause state; see watch_active. "
            "Written via PUT /info-items/{id}/watch-spec."
        )
    )
    watch_active: bool | None = Field(
        default=None,
        description=(
            "Per-item pause state. True schedules, false is registered-but-paused, "
            "and null means the registry has no opinion yet (not imported from Watcher). "
            "A sibling of watch_spec rather than a key inside it: a policy document "
            "shared across items could not carry per-item pause state. "
            "Written via PUT /info-items/{id}/watch-active."
        ),
    )
    created_at: datetime = Field(description="UTC timestamp when the InfoItem was created.")
    updated_at: datetime = Field(description="UTC timestamp of the last update to the InfoItem.")
    info_item_sources: list[InfoItemSourceOut] = Field(
        default_factory=list,
        description=(
            "Bound InfoSources. By default only active bindings are returned "
            "(is_active=true). Pass include_deactivated=true to also include previous "
            "primaries and other deactivated bindings. At most one active binding "
            "(is_active=true) exists — the current primary. Deactivated bindings "
            "(is_active=false) are previous primaries, preserved as succession history."
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
