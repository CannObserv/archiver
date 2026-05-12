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

from fastapi import HTTPException
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


def raise_envelope(
    status_code: int,
    kind: Kind,
    message: str,
    *,
    errors: list[dict[str, Any]] | list[FieldError] | None = None,
    data: dict[str, Any] | None = None,
    source_exc: BaseException | None = None,
) -> None:
    """Raise an HTTPException whose ``detail`` is a serialized ErrorEnvelope.

    Pass ``source_exc`` (typically the ``e`` from an ``except X as e`` block)
    to preserve exception chaining (ruff B904).  Construct ``errors`` as either
    dicts or ``FieldError`` instances — both round-trip through Pydantic.
    """
    field_errors: list[FieldError] = []
    if errors:
        for item in errors:
            field_errors.append(item if isinstance(item, FieldError) else FieldError(**item))

    env = ErrorEnvelope(kind=kind, message=message, errors=field_errors, data=data)
    detail = env.model_dump(exclude_none=True)

    if source_exc is not None:
        raise HTTPException(status_code=status_code, detail=detail) from source_exc
    raise HTTPException(status_code=status_code, detail=detail)


def raise_422(
    message: str,
    *,
    kind: Kind = "schema",
    errors: list[dict[str, Any]] | list[FieldError] | None = None,
    data: dict[str, Any] | None = None,
    source_exc: BaseException | None = None,
) -> None:
    """Shorthand for the common 422 case.  Defaults to ``kind='schema'``."""
    raise_envelope(422, kind, message, errors=errors, data=data, source_exc=source_exc)
