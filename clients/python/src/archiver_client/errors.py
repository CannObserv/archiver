"""Typed exceptions raised by ArchiverClient."""

from __future__ import annotations

import json
from typing import Any


class InformationError(Exception):
    """Base error for the Information SDK.

    Carries the parsed error envelope as typed attributes when the response
    body matches the documented shape (see the Archiver service's
    ``src/api/errors.py::ErrorEnvelope``).  When parsing fails, ``kind`` is
    ``"unknown"`` and ``message`` carries the raw body's first 200 chars.

    ``.body`` keeps the raw (truncated) body text for debugging — distinct from
    the parsed ``.kind`` / ``.errors`` / ``.data`` attrs.  Useful when the
    envelope shape evolves and the SDK temporarily can't parse a new field.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        body: str | None = None,
        kind: str = "unknown",
        errors: list[dict[str, Any]] | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body
        self.kind = kind
        self.message = message
        self.errors = errors or []
        self.data = data


class AuthError(InformationError):
    """401 / 403 from the Archiver service."""


class NotFound(InformationError):
    """404 — referenced entity (InfoItem, InfoSource, RepSpec, assignment, …) missing."""


class ValidationError(InformationError):
    """422 — request body or path didn't validate."""


class Conflict(InformationError):
    """409 — duplicate resource (e.g. existing InfoSource for the same URL).

    Inspect ``.data`` for the existing-row pointer; e.g.
    ``data["existing_info_source_id"]`` on a duplicate-URL conflict.
    """


class ServerError(InformationError):
    """5xx from the Archiver service."""


def _parse_envelope(
    body_text: str,
) -> tuple[str, str, list[dict[str, Any]], dict[str, Any] | None]:
    """Return (kind, message, errors, data) parsed from an envelope body.

    Falls back to ``("unknown", body_text[:200], [], None)`` if the body
    doesn't match the documented shape.
    """
    try:
        parsed = json.loads(body_text)
        env = parsed.get("detail")
        if isinstance(env, dict) and "kind" in env and "message" in env:
            return (
                str(env["kind"]),
                str(env["message"]),
                list(env.get("errors") or []),
                env.get("data"),
            )
    except (json.JSONDecodeError, TypeError, AttributeError):
        pass
    return ("unknown", body_text[:200] or "HTTP error", [], None)


def error_from_response(status: int, body: bytes) -> InformationError:
    """Map an HTTP status + envelope body to the appropriate InformationError subclass."""
    body_text = body.decode("utf-8", errors="replace")[:2000]
    kind, message, errors, data = _parse_envelope(body_text)

    common = dict(status_code=status, body=body_text, kind=kind, errors=errors, data=data)

    if status in (401, 403):
        return AuthError(message, **common)
    if status == 404:
        return NotFound(message, **common)
    if status == 409:
        return Conflict(message, **common)
    if status == 422:
        return ValidationError(message, **common)
    if 500 <= status < 600:
        return ServerError(message, **common)
    return InformationError(message, **common)
