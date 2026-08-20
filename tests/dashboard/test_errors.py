"""Tests for the dashboard's HTML error pages (#178).

Every case here is a browser reaching a failure path. The API answers those with
the JSON envelope (`src/api/errors.py`); a browser must get HTML instead, and -
because `<body hx-boost="true">` makes nearly every dashboard request an htmx
one - the *shape* of that HTML depends on the `HX-Request` header: a full
standalone document for a hard load, a bare fragment for an htmx swap.

Two apps are exercised:

* a throwaway app wired exactly like `src/api/main.py` (handlers first,
  `register_dashboard` second) plus routes that fail on demand. Real dashboard
  routes cannot be made to raise on cue, and the wiring order is itself under
  test: `Exception` has one handler slot app-wide, so a dashboard handler that
  *replaced* rather than wrapped the API's would silently take `/api/v1` with it.
* the real `app`, for the paths no test route can reproduce - FastAPI's own 404
  on an unrouted `/dashboard/...` URL.
"""

import json
import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, Form
from fastapi.exceptions import RequestValidationError
from fastapi.responses import PlainTextResponse
from httpx import ASGITransport, AsyncClient
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.api.errors import raise_envelope, register_error_handlers
from src.api.main import app as real_app
from src.dashboard import errors as dashboard_errors
from src.dashboard.exceptions import DashboardNotFound
from src.dashboard.main import register_dashboard

# The text an operator must never see on an error page: the exception's own
# message. Diagnostics live in the log, keyed by the incident id.
_LEAK = "connection to fintel.example refused (password=hunter2)"


@pytest.fixture
def boom_app() -> FastAPI:
    """An app wired like the real one, with routes that fail on demand."""
    app = FastAPI()
    register_error_handlers(app)
    register_dashboard(app)

    @app.get("/dashboard/boom")
    async def _dashboard_boom() -> PlainTextResponse:
        raise RuntimeError(_LEAK)

    @app.get("/dashboard/conflict")
    async def _dashboard_conflict() -> PlainTextResponse:
        raise_envelope(409, "conflict", "An active binding already exists")

    @app.get("/dashboard/missing")
    async def _dashboard_missing() -> PlainTextResponse:
        raise DashboardNotFound("Information Item not found")

    @app.post("/dashboard/needs-form")
    async def _dashboard_needs_form(label: str = Form(...)) -> PlainTextResponse:
        return PlainTextResponse(label)

    @app.get("/dashboard/server-error")
    async def _dashboard_server_error() -> PlainTextResponse:
        raise_envelope(503, "server", "The registry is briefly unavailable")

    @app.get("/api/v1/boom")
    async def _api_boom() -> PlainTextResponse:
        raise RuntimeError(_LEAK)

    return app


@pytest.fixture
async def boom_client(boom_app):
    """Client that lets the handler answer instead of re-raising into the test.

    ``raise_app_exceptions`` defaults to True, which surfaces the exception in
    the test and never runs `ServerErrorMiddleware`'s handler - the thing under
    test.
    """
    transport = ASGITransport(app=boom_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _incident_id(body: str) -> str:
    """The incident id printed on an error page."""
    match = re.search(r"Incident <code[^>]*>([0-9a-f]{8})</code>", body)
    assert match, f"no incident id on the page:\n{body}"
    return match.group(1)


# ---------------------------------------------------------------------------
# Uncaught exceptions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dashboard_500_renders_html(boom_client):
    """A crash on a dashboard route answers a browser with an HTML page."""
    r = await boom_client.get("/dashboard/boom")

    assert r.status_code == 500
    assert r.headers["content-type"].startswith("text/html")
    assert "<!doctype html>" in r.text.lower()
    assert "Something went wrong" in r.text


@pytest.mark.asyncio
async def test_dashboard_500_never_leaks_the_exception(boom_client):
    """The exception text stays in the log; the page carries an id instead."""
    r = await boom_client.get("/dashboard/boom")

    assert _LEAK not in r.text
    assert "RuntimeError" not in r.text
    assert _incident_id(r.text)


@pytest.mark.asyncio
async def test_incident_id_reaches_the_log(boom_client, monkeypatch):
    """The id on the page is the one to grep the journal for, or it is theatre.

    Spies the module logger rather than using caplog: ``configure_logging()``
    replaces ``root.handlers``, which defeats pytest's capture handler once any
    test in the session has called it (the precedent is
    ``tests/api/test_delete_info_item.py``).
    """
    spy = MagicMock()
    monkeypatch.setattr(dashboard_errors.logger, "exception", spy)

    r = await boom_client.get("/dashboard/boom")

    spy.assert_called_once()
    assert spy.call_args.kwargs["extra"]["incident_id"] == _incident_id(r.text)
    assert spy.call_args.kwargs["exc_info"] is not None, "log the traceback beside the id"


@pytest.mark.asyncio
async def test_api_500_still_returns_the_json_envelope(boom_client):
    """`Exception` has one handler slot: the dashboard must wrap, not replace."""
    r = await boom_client.get("/api/v1/boom")

    assert r.status_code == 500
    assert r.headers["content-type"].startswith("application/json")
    assert r.json() == {
        "detail": {"kind": "server", "message": "internal server error", "errors": []}
    }


# ---------------------------------------------------------------------------
# HTTPException paths - FastAPI's own 404/405, and route-raised envelopes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unrouted_dashboard_url_renders_html(boom_client):
    """A mistyped dashboard URL is a browser in the wrong place, not a client bug."""
    r = await boom_client.get("/dashboard/no-such-page")

    assert r.status_code == 404
    assert r.headers["content-type"].startswith("text/html")
    assert "404" in r.text


@pytest.mark.asyncio
async def test_unrouted_api_url_still_returns_json(boom_client):
    r = await boom_client.get("/api/v1/no-such-route")

    assert r.status_code == 404
    assert r.json()["detail"]["kind"] == "lookup"


@pytest.mark.asyncio
async def test_method_not_allowed_on_dashboard_renders_html(boom_client):
    r = await boom_client.post("/dashboard/boom")

    assert r.status_code == 405
    assert r.headers["content-type"].startswith("text/html")


@pytest.mark.asyncio
async def test_route_raised_envelope_renders_html_with_its_message(boom_client):
    """`raise_envelope` in a dashboard route is author-written prose - show it."""
    r = await boom_client.get("/dashboard/conflict")

    assert r.status_code == 409
    assert r.headers["content-type"].startswith("text/html")
    assert "An active binding already exists" in r.text


@pytest.mark.asyncio
async def test_missing_form_field_renders_html(boom_client):
    """A validation error FastAPI raises before route code runs (#86's last arm)."""
    r = await boom_client.post("/dashboard/needs-form", data={})

    assert r.status_code == 422
    assert r.headers["content-type"].startswith("text/html")


@pytest.mark.asyncio
async def test_dashboard_not_found_keeps_its_message(boom_client):
    """`DashboardNotFound` still renders its own prose, now via the shared page."""
    r = await boom_client.get("/dashboard/missing")

    assert r.status_code == 404
    assert "Information Item not found" in r.text


# ---------------------------------------------------------------------------
# htmx: fragment shape and the toast
# ---------------------------------------------------------------------------


def _flash(response) -> dict:
    """The `showFlash` payload htmx will raise from this response."""
    return json.loads(response.headers["HX-Trigger"])["showFlash"]


@pytest.mark.asyncio
async def test_htmx_request_gets_a_fragment_not_a_document(boom_client):
    """A boosted swap puts the response inside `<body>`; a whole document there
    is at best redundant and at worst nested `<html>`. Send the inner block."""
    r = await boom_client.get("/dashboard/boom", headers={"HX-Request": "true"})

    assert r.status_code == 500
    assert r.headers["content-type"].startswith("text/html")
    assert "<!doctype" not in r.text.lower()
    assert "<html" not in r.text.lower()
    assert "Something went wrong" in r.text


@pytest.mark.asyncio
async def test_partial_failure_flashes_through_hx_trigger(boom_client):
    """htmx discards a non-2xx body, but it raises `HX-Trigger` events from any
    response - it reads that header before it decides whether to swap
    (`tests/js/htmx-error-trigger.test.js` drives the real library to prove it).
    So a failed partial speaks through the flash mechanism every other dashboard
    outcome uses, rather than a header of its own."""
    r = await boom_client.get("/dashboard/conflict", headers={"HX-Request": "true"})

    flash = _flash(r)
    assert flash["level"] == "error"
    assert flash["body"] == "An active binding already exists"


@pytest.mark.asyncio
async def test_partial_crash_flash_is_generic_and_carries_the_incident(boom_client):
    r = await boom_client.get("/dashboard/boom", headers={"HX-Request": "true"})

    body = _flash(r)["body"]
    assert _LEAK not in body
    assert _incident_id(r.text) in body


@pytest.mark.asyncio
async def test_deliberate_5xx_flash_carries_the_incident_too(boom_client):
    """The toast is the whole of what a partial failure shows: the body is
    discarded, so an incident id only on the page is one the operator cannot
    read."""
    r = await boom_client.get("/dashboard/server-error", headers={"HX-Request": "true"})

    assert _incident_id(r.text) in _flash(r)["body"]


@pytest.mark.asyncio
async def test_boosted_failure_does_not_flash(boom_client):
    """A boosted request swaps the error page in, which says it once already."""
    r = await boom_client.get(
        "/dashboard/boom", headers={"HX-Request": "true", "HX-Boosted": "true"}
    )

    assert "HX-Trigger" not in r.headers


@pytest.mark.asyncio
async def test_hard_load_failure_does_not_flash(boom_client):
    """No htmx on the wire, no one to read the header."""
    r = await boom_client.get("/dashboard/boom")

    assert "HX-Trigger" not in r.headers


@pytest.mark.asyncio
async def test_api_errors_never_flash(boom_client):
    """The flash is a dashboard affordance; the SDK reads the envelope."""
    r = await boom_client.get("/api/v1/boom", headers={"HX-Request": "true"})

    assert "HX-Trigger" not in r.headers


@pytest.mark.asyncio
async def test_deliberate_5xx_gets_an_incident_id(boom_client):
    """A 5xx a route *raised* still sends the operator to the log.

    The message is author-written, so it renders; what it cannot supply is the
    join to the traceback, which is the whole point of the id.
    """
    r = await boom_client.get("/dashboard/server-error")

    assert r.status_code == 503
    assert "The registry is briefly unavailable" in r.text
    assert _incident_id(r.text)


@pytest.mark.asyncio
async def test_deliberate_5xx_logs_the_traceback_with_the_id(boom_client, monkeypatch):
    """Logging the message alone tells the operator what the page already did."""
    spy = MagicMock()
    monkeypatch.setattr(dashboard_errors.logger, "exception", spy)

    r = await boom_client.get("/dashboard/server-error")

    spy.assert_called_once()
    assert spy.call_args.kwargs["extra"]["incident_id"] == _incident_id(r.text)
    assert spy.call_args.kwargs["exc_info"] is not None


@pytest.mark.asyncio
async def test_405_keeps_its_allow_header(boom_client):
    """`Allow` is required on a 405 (RFC 9110) and rides on the exception."""
    r = await boom_client.post("/dashboard/boom")

    assert r.status_code == 405
    assert "GET" in r.headers.get("allow", "")


# ---------------------------------------------------------------------------
# Header encoding
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_toast_text_survives_the_header_verbatim(boom_client):
    """Headers are latin-1, and this one carried an em dash to operators as `?`.

    `json.dumps` defaults to `ensure_ascii=True`, so routing the toast through
    `HX-Trigger` makes the whole class unrepresentable rather than merely
    absent - which is the reason to prefer it over a header written by hand.
    """
    r = await boom_client.get("/dashboard/boom", headers={"HX-Request": "true"})

    incident = _incident_id(r.text)
    assert _flash(r)["body"] == f"Something went wrong - incident {incident}."


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    ["/dashboard/boom", "/dashboard/conflict", "/dashboard/missing", "/dashboard/server-error"],
)
async def test_every_error_header_is_ascii(boom_client, path):
    """A `?` in a toast is a character the header could not carry.

    Asserted on the wire rather than by scanning source for em dashes: this
    holds whatever anyone types, including text interpolated from a row.
    """
    r = await boom_client.get(path, headers={"HX-Request": "true"})

    for name, value in r.headers.items():
        assert value.isascii(), f"non-ASCII in {name}: {value!r}"


def test_theme_boot_is_shared_not_copied():
    """One FOUC script, included twice - `_error.html` cannot extend base.html.

    As two copies, the next change to the storage key or the class names fixes
    the page an operator sees every day and leaves the one they see when
    something has already gone wrong.
    """
    templates = Path(__file__).resolve().parents[2] / "src/dashboard/templates"
    boot = templates / "_theme_boot.html"

    assert boot.exists(), "the shared theme-boot partial is missing"
    assert "co-color-scheme" in boot.read_text()
    for name in ("base.html", "_error.html"):
        assert "_theme_boot.html" in (templates / name).read_text(), (
            f"{name} must include the shared partial, not carry its own copy"
        )
    assert "co-color-scheme" not in (templates / "_error.html").read_text()


@pytest.mark.asyncio
async def test_standalone_page_applies_the_operator_theme(boom_client):
    """The error page is the worst moment to flash the wrong colour scheme.

    `_error.html` cannot extend `base.html`, so the FOUC-prevention script is
    copied into it; without that, layer 3 of the theming system (the explicit
    `co-color-scheme` choice) does not apply and a dark-mode operator gets a
    white page.
    """
    r = await boom_client.get("/dashboard/boom")

    assert "co-color-scheme" in r.text


# ---------------------------------------------------------------------------
# The real app
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_real_app_unrouted_dashboard_url_renders_html(client):
    """Same assertion against the shipped wiring, not a hand-built app."""
    r = await client.get("/dashboard/definitely-not-a-page")

    assert r.status_code == 404
    assert r.headers["content-type"].startswith("text/html")


@pytest.mark.asyncio
async def test_real_app_api_404_still_returns_json(client):
    r = await client.get("/api/v1/definitely-not-a-route")

    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")


def test_base_html_loads_the_scripts_that_surface_failures():
    """Both halves of the toast path are a `<script>` tag away from silence.

    `htmx-errors.js` is what turns a refused swap into something visible, and it
    speaks through `flash.js`. Dropping either from the list breaks the other's
    only delivery route, with no error anywhere - the failure mode archiver#62
    recorded for `flash.js` alone.
    """
    base = (Path(__file__).resolve().parents[2] / "src/dashboard/templates/base.html").read_text()

    for script in ("flash.js", "htmx-errors.js"):
        assert script in base, f"base.html must load {script}"


def test_dashboard_handlers_are_the_installed_ones():
    """The dashboard wrapper, not the API handler, must hold each slot.

    Registration order decides this: `register_dashboard(app)` runs after
    `register_error_handlers(app)` in `src/api/main.py`, and swapping the two
    would put the API handlers back on top with every behavioural test in this
    file still passing for `/api/v1` and none of them passing for `/dashboard`.
    """
    installed = real_app.exception_handlers

    assert installed[Exception] is dashboard_errors.dashboard_unhandled_exception
    assert installed[StarletteHTTPException] is dashboard_errors.dashboard_http_exception
    assert installed[RequestValidationError] is dashboard_errors.dashboard_request_validation
    assert installed[DashboardNotFound] is dashboard_errors.dashboard_not_found
