"""HTML error pages for `/dashboard`, wrapping the API's JSON handlers (#178).

FastAPI exception handlers are app-wide and there is exactly **one slot per
exception class** — ``add_exception_handler(Exception, ...)`` assigns, it does
not append. So a dashboard handler cannot simply be *added*: registering a
second one would take `/api/v1` with it and answer the SDK with HTML. Each
handler here therefore branches on the path and delegates the non-dashboard case
straight back to `src/api/errors.py`. Registration order is load-bearing —
`register_dashboard(app)` runs after `register_error_handlers(app)` in
`src/api/main.py`, so these wrappers are the ones installed.

Three classes are wrapped, because all three answer a browser today:

* ``Exception`` — the crash the issue was filed about.
* ``StarletteHTTPException`` — FastAPI's own 404 on a mistyped `/dashboard/...`
  URL, its 405, and any ``raise_envelope`` a dashboard route makes.
* ``RequestValidationError`` — the one arm `src/dashboard/pagination.py` could
  not close by clamping: a `Form(...)` field that never arrives.

**Shape depends on `HX-Request`.** `<body hx-boost="true">` makes nearly every
dashboard request an htmx one, and htmx swaps a response *into* the existing
document — a full `<!doctype html>` page nested in a `<body>` is at best
redundant. htmx requests therefore get `_error_body.html` alone; hard loads get
the standalone `_error.html`.

**And htmx will not swap a non-2xx at all** unless told to, which is why the
page alone is not the fix: see the `htmx:beforeSwap` listener in
`static/htmx-errors.js`. For a partial (non-boosted) failure that listener shows
a toast rather than swapping, and reads its text from the ``X-Error-Message``
header set here — the body is discarded before any JS could parse it.
"""

from __future__ import annotations

import http
import secrets
from pathlib import Path

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.api.errors import (
    http_exception_handler,
    request_validation_handler,
    unhandled_exception_handler,
)
from src.core.logging import get_logger
from src.dashboard.exceptions import DashboardNotFound

logger = get_logger(__name__)

DASHBOARD_PREFIX = "/dashboard"

# Header the toast reads. Not `HX-Trigger`: htmx's trigger handling is part of
# the response-swap path this listener exists precisely because it is skipped.
ERROR_MESSAGE_HEADER = "X-Error-Message"

_templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

_CRASH_HEADING = "Something went wrong"
_CRASH_MESSAGE = (
    "The dashboard could not complete that request. Nothing further was attempted; "
    "work already confirmed is unaffected."
)

# FastAPI's stock detail strings, which read as terse machine output on a page.
_STOCK_DETAIL = {
    "Not Found": "That page does not exist. It may have been renamed, or the ID may be wrong.",
    "Method Not Allowed": "That address does not accept this kind of request.",
}


def _is_dashboard(request: Request) -> bool:
    """Whether this request wants HTML rather than the JSON envelope."""
    return request.url.path.startswith(DASHBOARD_PREFIX)


def _heading_for(status_code: int) -> str:
    if status_code >= 500:
        return _CRASH_HEADING
    try:
        return f"{status_code} — {http.HTTPStatus(status_code).phrase}"
    except ValueError:
        return f"{status_code} — Error"


def _header_safe(text: str) -> str:
    """Fold a message into something a response header can carry.

    Headers are latin-1 and single-line. An en dash or a stray newline in an
    author's message would otherwise raise *inside the error handler*, which
    costs the operator the page as well as the request.
    """
    collapsed = " ".join(text.split())
    return collapsed.encode("latin-1", "replace").decode("latin-1")[:200]


def _render(
    request: Request,
    *,
    status_code: int,
    message: str,
    heading: str | None = None,
    incident_id: str | None = None,
    toast: str | None = None,
) -> Response:
    """Render the error page — full document, or bare block for an htmx swap."""
    template = "_error_body.html" if "HX-Request" in request.headers else "_error.html"
    return _templates.TemplateResponse(
        request,
        template,
        {
            "heading": heading or _heading_for(status_code),
            "message": message,
            "incident_id": incident_id,
        },
        status_code=status_code,
        headers={ERROR_MESSAGE_HEADER: _header_safe(toast or message)},
    )


async def dashboard_unhandled_exception(request: Request, exc: Exception) -> Response:
    """Uncaught exception: HTML + an incident id on `/dashboard`, else the envelope.

    The page never carries ``str(exc)`` — an exception message is as likely to
    hold a DSN or a bound parameter as anything an operator can act on. The id
    is the join: printed once here, logged once beside the traceback.
    """
    if not _is_dashboard(request):
        return await unhandled_exception_handler(request, exc)

    incident_id = secrets.token_hex(4)
    logger.exception(
        "Unhandled exception on a dashboard route",
        exc_info=exc,
        extra={"incident_id": incident_id, "path": request.url.path},
    )
    return _render(
        request,
        status_code=500,
        message=_CRASH_MESSAGE,
        incident_id=incident_id,
        toast=f"{_CRASH_HEADING} — incident {incident_id}.",
    )


async def dashboard_http_exception(request: Request, exc: StarletteHTTPException) -> Response:
    """HTTPException: the envelope's ``message`` is author-written prose — show it."""
    if not _is_dashboard(request):
        return await http_exception_handler(request, exc)

    detail = exc.detail
    if isinstance(detail, dict) and "message" in detail:
        message = str(detail["message"])
    elif isinstance(detail, str) and detail:
        message = _STOCK_DETAIL.get(detail, detail)
    else:
        message = _heading_for(exc.status_code)

    # A 5xx raised deliberately still deserves the incident id: the operator's
    # next move is the log either way.
    incident_id = None
    if exc.status_code >= 500:
        incident_id = secrets.token_hex(4)
        logger.error(
            "Server-error HTTPException on a dashboard route",
            extra={"incident_id": incident_id, "path": request.url.path, "detail": message},
        )

    return _render(request, status_code=exc.status_code, message=message, incident_id=incident_id)


async def dashboard_request_validation(request: Request, exc: RequestValidationError) -> Response:
    """A malformed request FastAPI rejects before any dashboard code runs.

    Reachable only through a form the browser did not fill as the template
    intended — every dashboard query param is a ``str`` that
    `src/dashboard/pagination.py` clamps by hand, pinned by
    ``test_no_dashboard_route_declares_a_coercible_param``. Rendering it is
    still better than the silence htmx gives a 422 nobody handles.
    """
    if not _is_dashboard(request):
        return await request_validation_handler(request, exc)

    fields = [str(err["loc"][-1]) for err in exc.errors() if err.get("loc")]
    named = ", ".join(dict.fromkeys(fields))
    message = (
        f"That form could not be submitted — check: {named}."
        if named
        else "That form could not be submitted."
    )
    return _render(request, status_code=422, message=message)


async def dashboard_not_found(request: Request, exc: DashboardNotFound) -> Response:
    """A dashboard route's own "no such row" — its message is the page's."""
    return _render(request, status_code=404, message=exc.message)


__all__ = [
    "ERROR_MESSAGE_HEADER",
    "dashboard_http_exception",
    "dashboard_not_found",
    "dashboard_request_validation",
    "dashboard_unhandled_exception",
]
