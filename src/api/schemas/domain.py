"""Pydantic IO schemas for /api/v1/domains endpoints."""

from datetime import datetime

from pydantic import BaseModel, Field


class DomainPatch(BaseModel):
    """Request body for PATCH /domains/{name} — upsert fields."""

    model_config = {"extra": "forbid"}

    notes: str | None = Field(default=None, description="Operator annotations.")
    is_active: bool | None = Field(default=None, description="Gates inclusion in suggestions.")


class DomainOut(BaseModel):
    """Projection of a domains row."""

    id: str = Field(description="ULID identifying this Domain.")
    name: str = Field(description="Hostname (e.g. regulations.cannabis.ca.gov).")
    notes: str | None = Field(description="Operator annotations.")
    is_active: bool = Field(description="True when active and included in suggestions.")
    archived_at: datetime | None = Field(description="Set when the domain is archived.")
    created_at: datetime = Field(description="UTC timestamp when the Domain was created.")
    updated_at: datetime = Field(description="UTC timestamp of the last update.")
