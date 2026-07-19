"""Pydantic IO schemas for the /health endpoint."""

from pydantic import BaseModel, Field


class HealthOut(BaseModel):
    """Response body for GET /health."""

    status: str = Field(description="Liveness indicator; always 'ok' when the process is up.")
    build_id: str | None = Field(
        description=(
            "Deployed build identifier from the BUILD_ID environment variable "
            "(git describe --always --dirty at service start). Null when unset."
        ),
    )
