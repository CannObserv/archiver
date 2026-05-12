"""Integration tests for the global FastAPI exception handlers.

Uses a throwaway FastAPI app (not the real Archiver app) so we can register
endpoints that deliberately raise / 404 / 405 without touching production routes.
"""

from __future__ import annotations

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.testclient import TestClient

from src.api.errors import register_error_handlers


def _build_app() -> FastAPI:
    app = FastAPI()
    register_error_handlers(app)

    router = APIRouter()

    @router.get("/raise-http-string")
    def _raise_http_string():
        raise HTTPException(status_code=404, detail="thing not found")

    @router.get("/raise-http-envelope")
    def _raise_http_envelope():
        raise HTTPException(
            status_code=404,
            detail={"kind": "lookup", "message": "thing not found", "errors": []},
        )

    @router.post("/needs-body")
    def _needs_body(body: dict):  # noqa: ARG001 — body only used for Pydantic validation
        return {"ok": True}

    @router.get("/boom")
    def _boom():
        raise RuntimeError("internal kaboom")

    app.include_router(router)
    return app


def test_handler_wraps_bare_string_detail_into_envelope():
    client = TestClient(_build_app(), raise_server_exceptions=False)
    r = client.get("/raise-http-string")
    assert r.status_code == 404
    body = r.json()
    assert body["detail"]["kind"] == "lookup"
    assert body["detail"]["message"] == "thing not found"
    assert body["detail"]["errors"] == []


def test_handler_passes_envelope_detail_through_unchanged():
    client = TestClient(_build_app(), raise_server_exceptions=False)
    r = client.get("/raise-http-envelope")
    assert r.status_code == 404
    body = r.json()
    assert body["detail"] == {
        "kind": "lookup",
        "message": "thing not found",
        "errors": [],
    }


def test_handler_handles_fastapi_unmatched_route_404():
    """FastAPI raises its own HTTPException for unmatched routes — must be enveloped."""
    client = TestClient(_build_app(), raise_server_exceptions=False)
    r = client.get("/totally-not-a-route")
    assert r.status_code == 404
    body = r.json()
    assert body["detail"]["kind"] == "lookup"
    assert body["detail"]["errors"] == []


def test_handler_handles_method_not_allowed_405():
    client = TestClient(_build_app(), raise_server_exceptions=False)
    r = client.delete("/raise-http-string")
    assert r.status_code == 405
    body = r.json()
    # 405 maps to kind="unimplemented" (closest semantic fit in the closed set).
    assert body["detail"]["kind"] == "unimplemented"


def test_request_validation_error_becomes_kind_body():
    client = TestClient(_build_app(), raise_server_exceptions=False)
    r = client.post("/needs-body", content="not-json", headers={"content-type": "application/json"})
    assert r.status_code == 422
    body = r.json()
    assert body["detail"]["kind"] == "body"
    assert body["detail"]["errors"]  # at least one field error
    assert all("path" in e and "message" in e for e in body["detail"]["errors"])


def test_unhandled_exception_becomes_kind_server_500():
    client = TestClient(_build_app(), raise_server_exceptions=False)
    r = client.get("/boom")
    assert r.status_code == 500
    body = r.json()
    assert body["detail"] == {
        "kind": "server",
        "message": "internal server error",
        "errors": [],
    }


def test_handler_handles_bare_string_422_falls_back_to_kind_body():
    """A route raising HTTPException(status_code=422, detail='...') falls into the
    fallback branch — _kind_for_status maps 422 to 'body' when the route didn't
    set its own kind."""
    app = FastAPI()
    register_error_handlers(app)
    router = APIRouter()

    @router.get("/raise-bare-422")
    def _raise_bare_422():
        raise HTTPException(status_code=422, detail="explicit bare string at 422")

    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/raise-bare-422")
    assert r.status_code == 422
    assert r.json()["detail"]["kind"] == "body"
    assert r.json()["detail"]["message"] == "explicit bare string at 422"


def test_handler_handles_non_string_non_envelope_detail():
    """Non-dict non-string detail (e.g. a list) falls back to the HTTPStatus phrase."""
    app = FastAPI()
    register_error_handlers(app)
    router = APIRouter()

    @router.get("/raise-list-detail")
    def _raise_list_detail():
        raise HTTPException(status_code=404, detail=["unexpected", "list"])

    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/raise-list-detail")
    assert r.status_code == 404
    body = r.json()
    assert body["detail"]["kind"] == "lookup"
    assert body["detail"]["message"] == "Not Found"  # http.HTTPStatus(404).phrase
