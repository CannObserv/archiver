"""Pydantic IO schemas for the /health endpoint."""

from pydantic import BaseModel, Field


class HealthOut(BaseModel):
    """Response body for GET /health."""

    status: str = Field(description="Liveness indicator; always 'ok' when the process is up.")
    build_id: str | None = Field(
        description=(
            "Deployed build identifier: the serving release's REVISION, the "
            "12-character commit SHA scripts/deploy.sh writes into each release "
            "(archiver#330). Null outside a release (a dev server, the test suite)."
        ),
    )
