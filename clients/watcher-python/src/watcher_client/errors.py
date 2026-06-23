"""Typed exceptions raised by WatcherClient."""

from __future__ import annotations

import json
from typing import Any


class WatcherError(Exception):
    """Base error for the Watcher SDK.

    Carries the parsed error envelope as typed attributes when the response
    body matches the Watcher service's documented shape. When parsing fails,
    ``kind`` is ``"unknown"`` and ``message`` carries the raw body's first
    200 chars.
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


class WatcherAuthError(WatcherError):
    """401 / 403 from the Watcher service."""


class WatcherNotFound(WatcherError):
    """404 — WatchedItem or resource not found."""


class WatcherValidationError(WatcherError):
    """422 — request body or path didn't validate."""


class WatcherConflict(WatcherError):
    """409 — duplicate or state conflict (e.g. archived WatchedItem)."""


class WatcherServerError(WatcherError):
    """5xx from the Watcher service."""


class WatcherResponseError(WatcherError):
    """A 2xx response whose body could not be parsed into the expected model.

    Signals a response/SDK contract drift — the Watcher API changed shape and the
    generated ``watcher_client`` is stale — as opposed to a transport outage or an
    HTTP error status. Regenerate the SDK (``clients/watcher-python/scripts/regen.sh``)
    when this is raised.
    """


def _parse_detail(body_text: str) -> tuple[str, str, list[dict[str, Any]], dict[str, Any] | None]:
    """Return (kind, message, errors, data) from a response body.

    Falls back to ``("unknown", body_text[:200], [], None)`` on parse failure.
    """
    try:
        parsed = json.loads(body_text)
        detail = parsed.get("detail")
        if isinstance(detail, dict) and "kind" in detail and "message" in detail:
            return (
                str(detail["kind"]),
                str(detail["message"]),
                list(detail.get("errors") or []),
                detail.get("data"),
            )
        if isinstance(detail, str):
            return ("unknown", detail, [], None)
    except (json.JSONDecodeError, TypeError, AttributeError):
        pass
    return ("unknown", body_text[:200] or "HTTP error", [], None)


def error_from_response(status: int, body: bytes) -> WatcherError:
    """Map an HTTP status + body to the appropriate WatcherError subclass."""
    body_text = body.decode("utf-8", errors="replace")[:2000]
    kind, message, errors, data = _parse_detail(body_text)
    common = dict(status_code=status, body=body_text, kind=kind, errors=errors, data=data)

    if status in (401, 403):
        return WatcherAuthError(message, **common)
    if status == 404:
        return WatcherNotFound(message, **common)
    if status == 409:
        return WatcherConflict(message, **common)
    if status == 422:
        return WatcherValidationError(message, **common)
    if 500 <= status < 600:
        return WatcherServerError(message, **common)
    return WatcherError(message, **common)
