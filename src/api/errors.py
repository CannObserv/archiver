"""Service-wide error envelope models + raise helper + exception handlers.

Every non-2xx response the Archiver service emits is shaped by ``ErrorEnvelope``.
Route handlers raise via ``raise_envelope`` (or ``raise_422`` for the common
422 case); the global exception handlers in ``register_error_handlers`` wrap
anything that escapes those helpers (FastAPI's own 404/405, uncaught
exceptions) into the same envelope so the SDK only has to learn one shape.

See ``docs/plans/2026-05-12-issue-15-normalize-error-envelopes.md`` for the
contract.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Kind = Literal[
    "body",
    "schema",
    "domain",
    "lookup",
    "conflict",
    "auth",
    "unimplemented",
    "server",
]


class FieldError(BaseModel):
    """Single field-level validation problem."""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(description="JSON-Pointer style path to the offending field.")
    message: str = Field(description="Human-readable error message.")
    code: str | None = Field(
        default=None,
        description="Optional short machine-readable token (e.g. 'required').",
    )


class ErrorEnvelope(BaseModel):
    """Unified error response body."""

    model_config = ConfigDict(extra="forbid")

    kind: Kind = Field(description="Discriminator for client-side switching.")
    message: str = Field(description="Human-readable summary; safe to surface to users.")
    errors: list[FieldError] = Field(
        default_factory=list,
        description="Field-level problems; empty list when none apply.",
    )
    data: dict[str, Any] | None = Field(
        default=None,
        description="Optional kind-specific structured payload (e.g. conflict id).",
    )
