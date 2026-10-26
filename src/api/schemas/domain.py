"""Pydantic IO schemas for /api/v1/domains endpoints."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

_IS_ACTIVE = (
    "Suspension lever (archiver#360). false suspends the host: every Information "
    "Item announced on it goes out with active=false on info.registry, whatever "
    "its own watch_active. Archiving suspends it too."
)
_MIN_INTERVAL = (
    "Minimum spacing between requests to this host, in seconds (finite, >= 0; "
    "default 1.0). Live: Archiver publishes it on content.fetch-policy (#366, "
    "since flip F1), and a suspended host publishes revoked with no interval."
)
_DEFAULT_WATCH_SPEC = (
    "Default cadence for Information Items on this host: a WatchSpec v1 document "
    "that carries an interval, or null for no domain default. Dark until cadence "
    "resolution (#364, flip F2) reads it."
)


class DomainPatch(BaseModel):
    """Request body for PATCH /domains/{name} — upsert fields.

    An omitted field is left as it is. ``default_watch_spec: null`` clears the
    cadence; ``min_interval_seconds`` cannot be null (every host carries an
    explicit policy).
    """

    model_config = {"extra": "forbid"}

    notes: str | None = Field(default=None, description="Operator annotations.")
    is_active: bool | None = Field(default=None, description=_IS_ACTIVE)
    # Optional but not nullable: an explicit null fails the float check (422).
    # default_factory, not default=None, keeps "default: null" out of the
    # OpenAPI schema - the SDK would otherwise type it nullable.
    min_interval_seconds: float = Field(
        default_factory=lambda: None, ge=0, allow_inf_nan=False, description=_MIN_INTERVAL
    )
    default_watch_spec: dict[str, Any] | None = Field(default=None, description=_DEFAULT_WATCH_SPEC)


class DomainOut(BaseModel):
    """Projection of a domains row."""

    id: str = Field(description="ULID identifying this Domain.")
    name: str = Field(description="Hostname (e.g. regulations.cannabis.ca.gov).")
    notes: str | None = Field(description="Operator annotations.")
    is_active: bool = Field(description=_IS_ACTIVE)
    archived_at: datetime | None = Field(
        description="Set when the domain is archived; an archived host is suspended."
    )
    min_interval_seconds: float = Field(description=_MIN_INTERVAL)
    default_watch_spec: dict[str, Any] | None = Field(description=_DEFAULT_WATCH_SPEC)
    created_at: datetime = Field(description="UTC timestamp when the Domain was created.")
    updated_at: datetime = Field(description="UTC timestamp of the last update.")
