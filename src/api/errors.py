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

import http
from typing import Any, Literal, NoReturn

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.core.logging import get_logger

logger = get_logger(__name__)

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

    model_config = {"extra": "forbid"}

    path: str = Field(description="JSON-Pointer style path to the offending field.")
    message: str = Field(description="Human-readable error message.")
    code: str | None = Field(
        default=None,
        description="Optional short machine-readable token (e.g. 'required').",
    )


class ErrorEnvelope(BaseModel):
    """Unified error response body."""

    model_config = {"extra": "forbid"}

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


class EnvelopeResponse(BaseModel):
    """Outer ``{"detail": ErrorEnvelope}`` wrapper for OpenAPI docs.

    Public name (no leading underscore) so ``openapi-python-client`` generates a
    cleanly-named SDK model — the class name is what surfaces in
    ``components/schemas`` and feeds the SDK code generator.
    """

    detail: ErrorEnvelope


def raise_envelope(
    status_code: int,
    kind: Kind,
    message: str,
    *,
    errors: list[dict[str, Any]] | list[FieldError] | None = None,
    data: dict[str, Any] | None = None,
    source_exc: BaseException | None = None,
) -> NoReturn:
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
) -> NoReturn:
    """Shorthand for the common 422 case.  Defaults to ``kind='schema'``."""
    raise_envelope(422, kind, message, errors=errors, data=data, source_exc=source_exc)


_STATUS_TO_KIND: dict[int, Kind] = {
    401: "auth",
    403: "auth",
    404: "lookup",
    405: "unimplemented",
    409: "conflict",
    501: "unimplemented",
}


def _kind_for_status(status_code: int) -> Kind:
    """Status → kind mapping for HTTPExceptions that didn't set their own envelope.

    Note 405 → ``unimplemented``: the closed ``Kind`` set has no ``method_not_allowed``
    bucket, and 405 most often surfaces because a verb genuinely isn't supported on
    that route — semantically closer to "not implemented" than to auth.  If we ever
    need a finer split, add a kind value and update this map.
    """
    if status_code in _STATUS_TO_KIND:
        return _STATUS_TO_KIND[status_code]
    if 500 <= status_code < 600:
        return "server"
    if status_code == 422:
        return "body"  # only used if a bare-string 422 escapes — routes should set their own kind.
    # Fallback: treat as generic 4xx -> "lookup" (matches the most common case).
    return "lookup"


def _pointer_from_loc(loc: tuple[str | int, ...]) -> str:
    """Convert a Pydantic ``loc`` tuple to a JSON-Pointer string.

    Drops the leading source-frame token (``body``/``query``/``path``/``header``)
    so the path is meaningful to the API consumer.  Returns ``""`` for
    document-level errors.
    """
    if not loc:
        return ""
    parts = loc[1:] if loc and loc[0] in {"body", "query", "path", "header", "cookie"} else loc
    if not parts:
        return ""
    return "/" + "/".join(str(p) for p in parts)


async def request_validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    errors = [
        FieldError(
            path=_pointer_from_loc(tuple(e["loc"])),
            message=e["msg"],
            code=e.get("type"),
        )
        for e in exc.errors()
    ]
    env = ErrorEnvelope(kind="body", message="invalid request body", errors=errors)
    return JSONResponse(status_code=422, content={"detail": env.model_dump(exclude_none=True)})


async def http_exception_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Wrap any HTTPException whose ``detail`` isn't already an envelope.

    Route code that already calls ``raise_envelope``/``raise_422`` passes a dict
    matching the envelope shape — we recognize that and pass it through.
    Bare-string ``detail`` values (FastAPI's own 404/405, plus any residual route
    code) get wrapped here.
    """
    detail = exc.detail
    if isinstance(detail, dict) and "kind" in detail and "message" in detail:
        # Already envelope-shaped — pass through verbatim.
        return JSONResponse(status_code=exc.status_code, content={"detail": detail})

    if isinstance(detail, str):
        message = detail
    else:
        try:
            message = http.HTTPStatus(exc.status_code).phrase
        except ValueError:
            message = "error"
    env = ErrorEnvelope(kind=_kind_for_status(exc.status_code), message=message, errors=[])
    return JSONResponse(
        status_code=exc.status_code, content={"detail": env.model_dump(exclude_none=True)}
    )


async def unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    """Catch-all: log the traceback, return a generic 500 envelope.

    Never leak ``str(exc)`` into the response — diagnostics live in logs only.
    """
    logger.exception("Unhandled exception in request handler", exc_info=exc)
    env = ErrorEnvelope(kind="server", message="internal server error", errors=[])
    return JSONResponse(status_code=500, content={"detail": env.model_dump(exclude_none=True)})


def register_error_handlers(app: FastAPI) -> None:
    """Attach the three global handlers to ``app``.

    Must be called once during app construction, *after* ``app = FastAPI(...)``.
    """
    app.add_exception_handler(RequestValidationError, request_validation_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
