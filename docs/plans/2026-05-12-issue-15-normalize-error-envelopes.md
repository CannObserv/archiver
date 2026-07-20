# Normalize Error Response Envelopes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every non-2xx response from the Archiver service emit the same JSON envelope, and update the SDK to consume it as typed attributes.

**Architecture:** One Pydantic model — `ErrorEnvelope { kind, message, errors[], data }` — wraps every error body the service emits. Three FastAPI exception handlers (`RequestValidationError`, `HTTPException`, `Exception`) own the wrapping; route code keeps using `HTTPException` (raised through new `raise_envelope`/`raise_422` helpers) but never constructs envelope dicts by hand. SDK `error_from_response` parses the envelope and surfaces `.kind` / `.message` / `.errors` / `.data` on every `InformationError` subclass. Atomic flip, no fallback parser, no per-route flag — pre-production permits breaking changes.

**Tech Stack:** FastAPI · Pydantic v2 · pytest · openapi-python-client · httpx · respx.

---

## Context for the implementer

This plan is the resolution of GitHub issue #15. Reading the issue first will save you reverse-engineering the motivation.

**Why this exists:** the service today emits **four** different shapes for 422 alone — `{message, errors[]}`, `{error, errors[]}`, `{missing: [...]}`, and `{detail: "<bare string>"}` for malformed ULIDs — plus a fifth shape for 409 (`{message, url, existing_info_source_id}`), bare strings for 401/403/404/501/5xx, and FastAPI's default for unmatched routes (404) and wrong methods (405). SDK consumers cannot write one parser. We're pre-production so we will flip atomically rather than add a compatibility layer.

**Reference docs you should read before starting:**
- The issue itself: `gh issue view 15` (the body lists the surfaces).
- `CLAUDE.md` (repo root) — covers TDD discipline, commit-message format (`#15 [type]: ...`), the `raise ... from e` chaining ruff B904 rule, the dev-server lifecycle, env loading.
- `docs/plans/2026-05-11-issue-10-rep-spec-authoring-endpoints.md` — most recent plan, this plan mirrors its task style.
- `src/api/routes/rep_specs.py:26-62` — the docstring there already calls out the inconsistency we're fixing.

**Skills to invoke as you go:**
- `superpowers:test-driven-development` — Red → Green → Refactor on every task.
- `superpowers:verification-before-completion` — never claim a task is done before the listed commands have run green.
- `superpowers:systematic-debugging` — when anything fails to behave as the plan claims.

**Working directory & port discipline:**
- Production lives on port 8020 under systemd; the agent dev server runs on 8021 (manual uvicorn). Never bind 8020.
- Two env files load in order: `/etc/archiver/.env` then `.env`. Standard incantation: `export $(cat /etc/archiver/.env .env 2>/dev/null | xargs)`.

**Branch:** use a worktree per `superpowers:using-git-worktrees`. Suggested branch name: `issue-15-normalize-error-envelopes`.

---

## Envelope contract

Every error response body, regardless of status code:

```json
{
  "detail": {
    "kind": "body" | "schema" | "domain" | "lookup" | "conflict" | "auth" | "unimplemented" | "server",
    "message": "human-readable, safe to surface to users",
    "errors": [
      {"path": "/document/provider", "message": "...", "code": "optional_short_token"}
    ],
    "data": {"optional": "kind-specific payload"}
  }
}
```

Field semantics:
- `detail` — the outer key FastAPI uses by convention. We keep it so we can keep raising `HTTPException(status_code=…, detail=…)` inside routes; the global handler just wraps it.
- `kind` — discriminator the SDK switches on. Eight values, closed set, listed above.
- `message` — one human sentence. Never includes a stack trace or internal path. For 5xx it is the literal string `"internal server error"` — diagnostics go to logs only.
- `errors` — always present, always a list. Empty list for kinds with no field-level info (auth, lookup, server). Each element is a `FieldError` (see schema below). For multi-issue validators (rep_spec, source_spec, Pydantic) each field gets its own entry.
- `data` — optional dict slot for kind-specific structured extras. Today only 409 uses it (`{"url": "...", "existing_info_source_id": "..."}`). Stays absent (omitted from JSON) when there is nothing to put there.

Status-code → kind mapping (the global handler enforces this):

| Status | kind |
|--------|------|
| 401, 403 | `auth` |
| 404 | `lookup` |
| 409 | `conflict` |
| 422 (Pydantic body) | `body` |
| 422 (schema validators: SourceSpec, RepSpec) | `schema` |
| 422 (domain errors: rep_fields_incomplete, target_unreachable, ParentMustBeRoot, malformed ULID in path) | `domain` |
| 501 | `unimplemented` |
| 5xx | `server` |

`FieldError`:
- `path: str` — JSON-Pointer style (`""` for whole-document, `/foo/0/bar` for nested). For Pydantic errors derive from `loc[1:]` (strip the `"body"`/`"path"`/`"query"` prefix so we don't leak FastAPI internals).
- `message: str` — human-readable.
- `code: str | None` — short machine-readable token (`"required"`, `"target_unreachable"`, `"rep_fields_incomplete"`, etc.). Optional; omitted from JSON when None.

Both models live in `src/api/errors.py` and are exported by the OpenAPI schema as named components (`ErrorEnvelope`, `FieldError`) — load-bearing so `openapi-python-client` deserializes 4xx/5xx bodies into a single named class instead of one anonymous schema per route.

---

## File Structure

What you will create:

- `src/api/errors.py` — `ErrorEnvelope`, `FieldError` Pydantic models + the `raise_envelope(status, kind, message, errors=None, data=None, *, source_exc=None)` helper + the three exception handlers (`request_validation_handler`, `http_exception_handler`, `unhandled_exception_handler`) + a small `register_error_handlers(app)` shim called from `main.py`.
- `tests/api/test_error_envelope.py` — unit tests for the envelope models + the helper.
- `tests/api/test_error_handlers.py` — handler-level integration tests using `TestClient` against a throwaway FastAPI app (verifies 405, unmatched-route 404, uncaught Exception → 500 envelope).

What you will modify:

- `src/api/main.py` — call `register_error_handlers(app)` after the `app = FastAPI(...)` line.
- `src/api/routes/info_sources.py` — replace inline `HTTPException(..., detail=…)` calls with `raise_envelope(...)`. Five sites.
- `src/api/routes/info_items.py` — same. ~14 sites.
- `src/api/routes/rep_specs.py` — same. Two sites. Also strip the `See #15 for normalization plans.` note from the docstring.
- `src/api/routes/source_revisions.py` — same. Four sites.
- `src/api/routes/tools.py` — same. Three sites (preview-extraction × 2, fetch-and-render render-501).
- `src/api/deps.py` — same. Two sites (401, 403).
- `src/api/schemas/tools.py` — make `ValidationErrorOut` an alias / direct re-export of `FieldError` so the 200-success-shape schema and the error-envelope shape share one Pydantic model. (Strictly optional but worth it — single source of truth for `{path, message, code}`.)
- `tests/api/test_v2_endpoints.py` — every 422/404/409 assertion. Greppable: `assert response.status_code == 422` then `response.json()` introspection.
- `tests/api/test_rep_specs.py`, `tests/api/test_info_sources.py`, `tests/api/test_info_items.py`, `tests/api/test_source_revisions.py`, `tests/api/test_create_info_item_atomic.py` — same.
- `tests/api/test_tools_preview_extraction.py`, `tests/api/test_tools_fetch_and_render.py` — same. (Tool tests are split across `test_tools_<name>.py`; `test_tools.py` does **not** exist as a single file. Other tool test modules — `test_tools_find.py`, `test_tools_propose_selectors.py`, `test_tools_validate.py` — may or may not need changes depending on whether they assert error bodies; grep each before claiming done.)
- `tests/api/test_auth.py` — 401/403 assertions.
- `tests/api/test_exception_chaining.py` — assert chaining still works through the new helper (the helper preserves `__cause__` when given `source_exc=e`).
- `clients/python/src/archiver_client/errors.py` — `error_from_response` parses the envelope and stores `.kind`, `.message`, `.errors`, `.data` on every subclass.
- `clients/python/tests/test_errors.py` — rewrite to assert the parsed attrs (the current tests only check class + body presence).
- `clients/python/tests/test_client.py` — rewrite `test_get_info_item_422_raises_validation_error` (currently mocks the FastAPI default shape) and audit every other respx mock for legacy 4xx shapes.
- `clients/python/pyproject.toml` — bump `version = "2.0.0"`.
- `clients/python/README.md` — note the v2.0 breaking change in the version history block.
- `CLAUDE.md` — add a short "Error envelope" subsection to the Conventions section, and update the "SDK version history" line to mention v2.0.
- `scripts/smoke_phase4.sh` — only if it inspects error bodies anywhere (it shouldn't; it exercises 2xx paths).

After all server-side and SDK-helper changes are in: regenerate the SDK (`bash clients/python/scripts/regen.sh`), then update any generated-model-aware tests.

---

## Pre-flight checks

Before starting Task 1, in your worktree:

```bash
# Load env (production secrets path is /etc/archiver/.env; agent secrets path is .env).
export $(cat /etc/archiver/.env .env 2>/dev/null | xargs)

# Sanity: tests green at baseline.
uv run pytest -q
uv run ruff check .

# Confirm test DB is reachable.
uv run alembic upgrade head
```

Expected: all tests pass; `ruff check .` reports no findings; alembic reports `OK` (or no-op).

If any of the above fails, fix that first — it has nothing to do with this plan.

---

## Task 1: ErrorEnvelope + FieldError Pydantic models

**Files:**
- Create: `src/api/errors.py` (models only — handlers added in Task 3)
- Create: `tests/api/test_error_envelope.py`

The Pydantic models and the constant `Kind` literal alias. Pure data; no FastAPI imports yet.

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_error_envelope.py`:

```python
"""Pydantic-level tests for ErrorEnvelope + FieldError."""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from src.api.errors import ErrorEnvelope, FieldError


def test_field_error_minimal():
    fe = FieldError(path="/document/provider", message="must be one of: gcs, gdrive, ia")
    dumped = fe.model_dump(exclude_none=True)
    assert dumped == {"path": "/document/provider", "message": "must be one of: gcs, gdrive, ia"}


def test_field_error_with_code():
    fe = FieldError(path="", message="required", code="required")
    dumped = fe.model_dump(exclude_none=True)
    assert dumped == {"path": "", "message": "required", "code": "required"}


def test_envelope_minimal_omits_data_and_empty_errors_list_stays():
    env = ErrorEnvelope(kind="lookup", message="InfoItem not found")
    dumped = env.model_dump(exclude_none=True)
    # `errors` is always present (even when empty); `data` omitted.
    assert dumped == {"kind": "lookup", "message": "InfoItem not found", "errors": []}


def test_envelope_with_errors():
    env = ErrorEnvelope(
        kind="schema",
        message="invalid rep_spec",
        errors=[
            FieldError(path="/document/provider", message="missing required key"),
            FieldError(path="/document/path_template", message="must be non-empty"),
        ],
    )
    dumped = env.model_dump(exclude_none=True)
    assert dumped["kind"] == "schema"
    assert len(dumped["errors"]) == 2
    assert dumped["errors"][0]["path"] == "/document/provider"


def test_envelope_with_data():
    env = ErrorEnvelope(
        kind="conflict",
        message="an InfoSource already exists for this URL",
        data={"url": "https://example.com", "existing_info_source_id": "01HXX..."},
    )
    dumped = env.model_dump(exclude_none=True)
    assert dumped["data"]["existing_info_source_id"] == "01HXX..."


def test_envelope_rejects_unknown_kind():
    with pytest.raises(PydanticValidationError):
        ErrorEnvelope(kind="not-a-real-kind", message="x")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/api/test_error_envelope.py -v
```

Expected: ImportError / ModuleNotFoundError on `src.api.errors`.

- [ ] **Step 3: Write minimal implementation**

Create `src/api/errors.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/api/test_error_envelope.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/api/errors.py tests/api/test_error_envelope.py
git commit -m "#15 feat: ErrorEnvelope + FieldError Pydantic models"
```

---

## Task 2: raise_envelope + raise_422 helpers

**Files:**
- Modify: `src/api/errors.py` (add helpers)
- Modify: `tests/api/test_error_envelope.py` (add helper tests)

The helpers build the envelope and raise an `HTTPException(detail=envelope.model_dump(exclude_none=True))`. Routes never construct envelope dicts themselves.

- [ ] **Step 1: Add failing tests**

Append to `tests/api/test_error_envelope.py`:

```python
from fastapi import HTTPException

from src.api.errors import raise_422, raise_envelope


def test_raise_envelope_raises_http_exception_with_envelope_detail():
    with pytest.raises(HTTPException) as exc_info:
        raise_envelope(404, "lookup", "InfoItem not found")
    exc = exc_info.value
    assert exc.status_code == 404
    assert exc.detail == {"kind": "lookup", "message": "InfoItem not found", "errors": []}


def test_raise_envelope_preserves_cause_via_source_exc():
    """raise_envelope must chain via `from source_exc` so ruff B904 is satisfied."""
    src = ValueError("bad ulid")
    with pytest.raises(HTTPException) as exc_info:
        raise_envelope(422, "domain", "info_item_id is not a valid ULID", source_exc=src)
    assert exc_info.value.__cause__ is src


def test_raise_envelope_with_errors_and_data():
    fes = [{"path": "/foo", "message": "required", "code": "required"}]
    with pytest.raises(HTTPException) as exc_info:
        raise_envelope(
            409,
            "conflict",
            "duplicate",
            errors=fes,
            data={"existing_id": "01HXX..."},
        )
    detail = exc_info.value.detail
    assert detail["errors"] == fes
    assert detail["data"] == {"existing_id": "01HXX..."}


def test_raise_422_is_shorthand_for_kind_schema():
    """raise_422 defaults kind to 'schema'; can be overridden."""
    with pytest.raises(HTTPException) as exc_info:
        raise_422("invalid rep_spec", errors=[{"path": "/x", "message": "bad"}])
    detail = exc_info.value.detail
    assert exc_info.value.status_code == 422
    assert detail["kind"] == "schema"
    assert detail["message"] == "invalid rep_spec"


def test_raise_422_kind_override():
    with pytest.raises(HTTPException) as exc_info:
        raise_422("rep_fields incomplete", kind="domain", errors=[{"path": "/", "message": "x"}])
    assert exc_info.value.detail["kind"] == "domain"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/api/test_error_envelope.py -v
```

Expected: ImportError on `raise_envelope` / `raise_422`.

- [ ] **Step 3: Add the helpers to `src/api/errors.py`**

Append below the model definitions:

```python
from fastapi import HTTPException


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
    raise_envelope(
        422, kind, message, errors=errors, data=data, source_exc=source_exc
    )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/api/test_error_envelope.py -v
```

Expected: 11 passed (6 from Task 1 + 5 from Task 2).

- [ ] **Step 5: Commit**

```bash
git add src/api/errors.py tests/api/test_error_envelope.py
git commit -m "#15 feat: raise_envelope + raise_422 helpers"
```

---

## Task 3: Global exception handlers

**Files:**
- Modify: `src/api/errors.py` (add handlers + `register_error_handlers`)
- Modify: `src/api/main.py` (call `register_error_handlers(app)`)
- Create: `tests/api/test_error_handlers.py`

Three handlers in one module, registered together. The `HTTPException` handler is the load-bearing one — it wraps any plain-string `detail` (FastAPI's own 404/405, residual route code we haven't migrated yet) into the envelope.

- [ ] **Step 1: Write failing tests**

Create `tests/api/test_error_handlers.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/api/test_error_handlers.py -v
```

Expected: ImportError on `register_error_handlers`.

- [ ] **Step 3: Implement the handlers**

Append to `src/api/errors.py`:

```python
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.core.logging import get_logger

_logger = get_logger(__name__)


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


async def _request_validation_handler(
    _: Request, exc: RequestValidationError
) -> JSONResponse:
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


async def _http_exception_handler(
    _: Request, exc: StarletteHTTPException
) -> JSONResponse:
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

    message = detail if isinstance(detail, str) else "error"
    env = ErrorEnvelope(
        kind=_kind_for_status(exc.status_code), message=message, errors=[]
    )
    return JSONResponse(
        status_code=exc.status_code, content={"detail": env.model_dump(exclude_none=True)}
    )


async def _unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    """Catch-all: log the traceback, return a generic 500 envelope.

    Never leak ``str(exc)`` into the response — diagnostics live in logs only.
    """
    _logger.exception("Unhandled exception in request handler", exc_info=exc)
    env = ErrorEnvelope(kind="server", message="internal server error", errors=[])
    return JSONResponse(status_code=500, content={"detail": env.model_dump(exclude_none=True)})


def register_error_handlers(app: FastAPI) -> None:
    """Attach the three global handlers to ``app``.

    Must be called once during app construction, *after* ``app = FastAPI(...)``.
    """
    app.add_exception_handler(RequestValidationError, _request_validation_handler)
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
    app.add_exception_handler(Exception, _unhandled_exception_handler)
```

Then wire it into `src/api/main.py` — find the `app = FastAPI(...)` line near the bottom (currently around line 87) and add immediately after it:

```python
from src.api.errors import register_error_handlers  # add to imports up top

# ...

app = FastAPI(title="archiver", version=_package_version("archiver"), lifespan=lifespan)
register_error_handlers(app)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/api/test_error_handlers.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Run the full suite to confirm no incidental breaks**

```bash
uv run pytest -q
```

Expected: existing tests should still pass *for routes that already use dict ``detail``*. Routes still using bare-string ``detail`` are now silently being wrapped — many existing test assertions will start failing (`assert response.json()["detail"] == "InfoItem not found"` now sees `{"kind": "lookup", "message": "InfoItem not found", "errors": []}`). **That's expected** — those test updates are Tasks 4–10. Capture the failure list; you'll work through it route-by-route.

If the failure list looks materially bigger than ~70–100 assertions across the test directory, stop and re-read the handler — something is over-wrapping. (Greps suggest `test_v2_endpoints.py` ~19, `test_info_sources.py` ~26, `test_rep_specs.py` ~18, plus auth, tools, info_items, source_revisions, create_info_item_atomic.)

- [ ] **Step 6: Commit**

```bash
git add src/api/errors.py src/api/main.py tests/api/test_error_handlers.py
git commit -m "#15 feat: global error handlers (RequestValidationError + HTTPException + Exception)"
```

---

## Task 4: Migrate `src/api/deps.py` (auth: 401, 403)

**Files:**
- Modify: `src/api/deps.py:38-47`
- Modify: `tests/api/test_auth.py`

- [ ] **Step 1: Update test assertions to match the new envelope**

Open `tests/api/test_auth.py`. For each `assert response.json() == {...}` or `assert response.json()["detail"] == "..."` that targets a 401/403 from this service:

Replace assertions like:
```python
assert response.json() == {"detail": "Invalid API key"}
```
with:
```python
assert response.status_code == 401
body = response.json()
assert body["detail"]["kind"] == "auth"
assert body["detail"]["message"] == "Invalid API key"
assert body["detail"]["errors"] == []
```

If `tests/api/test_auth.py` does not exist or has no such assertions (auth tests may be tucked inside other modules), grep first:

```bash
rg -n "Invalid API key|Not authenticated" tests/
```

Update every hit accordingly.

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/api/test_auth.py -v   # or wherever the auth tests live
```

Expected: the new assertions fail because [deps.py](src/api/deps.py) still raises bare-string `HTTPException`s (which the global handler *does* wrap, but the route hasn't been migrated to set its own kind yet; the wrapper defaults 401/403 → `kind="auth"` already, so this step may already pass — verify, then move on).

If the test passes already at this step, the only remaining work in Task 4 is the cosmetic move to `raise_envelope` for consistency (Step 3). Run it anyway — never skip the structural change just because the wrapper masks it.

- [ ] **Step 3: Migrate `src/api/deps.py`**

Replace [deps.py:38-47](src/api/deps.py#L38-L47):

```python
from src.api.errors import raise_envelope


def require_api_key(raw_key: str | None = Depends(api_key_header)) -> None:
    """Validate X-API-Key against ARCHIVER_API_KEY env var.

    Raises 403 when the header is absent and 401 when it is present but invalid.
    """
    if raw_key is None:
        raise_envelope(403, "auth", "Not authenticated")
    expected = os.environ.get("ARCHIVER_API_KEY")
    if not expected or raw_key != expected:
        raise_envelope(401, "auth", "Invalid API key")
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/api/test_auth.py -v
```

Expected: green.

- [ ] **Step 5: Commit**

```bash
git add src/api/deps.py tests/api/test_auth.py   # add other test files if you updated them
git commit -m "#15 refactor: migrate auth deps to raise_envelope"
```

---

## Task 5: Migrate `src/api/routes/info_sources.py`

**Files:**
- Modify: `src/api/routes/info_sources.py` (5 raise sites)
- Modify: `tests/api/test_info_sources.py`

**Also touches** `tests/api/test_create_info_item_atomic.py` — specifically the 409-shape assertions around lines 203-205 (`detail["existing_info_source_id"]`, `detail["url"]`). These move under `detail["data"][...]` in the new envelope. Include this file in the test edit step below.

Sites to migrate (current → target):

| Line | Current detail | Target |
|------|----------------|--------|
| 59-61 | `"parent_info_source_id is not a valid ULID"` | `raise_envelope(422, "domain", "parent_info_source_id is not a valid ULID", errors=[FieldError(path="/parent_info_source_id", message="not a valid ULID", code="invalid_ulid")], source_exc=e)` |
| 70-73 | `{"message": "invalid source_spec", "errors": e.errors}` | `raise_422("invalid source_spec", kind="schema", errors=e.errors, source_exc=e)` |
| 75 | `"parent InfoSource not found"` | `raise_envelope(404, "lookup", "parent InfoSource not found", source_exc=e)` |
| 77-80 | `"parent_info_source_id must reference a root InfoSource"` | `raise_envelope(422, "domain", "parent_info_source_id must reference a root InfoSource", errors=[FieldError(path="/parent_info_source_id", message="must reference a root InfoSource", code="parent_must_be_root")], source_exc=e)` |
| 82-89 | conflict dict with `existing_info_source_id` | `raise_envelope(409, "conflict", "an InfoSource already exists for this URL", data={"url": e.url, "existing_info_source_id": str(e.existing_info_source_id)}, source_exc=e)` |
| 115-117 | `"parent_info_source_id is not a valid ULID"` (in list route) | same as line 59 |
| 139 | `"InfoSource not found"` | `raise_envelope(404, "lookup", "InfoSource not found")` |

- [ ] **Step 1: Update test assertions in `tests/api/test_info_sources.py`**

Run `rg -n 'response.json\\(\\)|json\\(\\)\\["detail"\\]|assert.*detail' tests/api/test_info_sources.py` and rewrite every assertion that touches the response body.

Examples of common rewrites:

```python
# Before:
assert response.json()["detail"] == "InfoSource not found"

# After:
body = response.json()
assert body["detail"]["kind"] == "lookup"
assert body["detail"]["message"] == "InfoSource not found"

# Before (409):
assert response.json()["detail"]["existing_info_source_id"] == ...

# After (409):
detail = response.json()["detail"]
assert detail["kind"] == "conflict"
assert detail["data"]["existing_info_source_id"] == ...

# Before (422 schema):
assert response.json()["detail"]["message"] == "invalid source_spec"
assert isinstance(response.json()["detail"]["errors"], list)

# After (422 schema):
detail = response.json()["detail"]
assert detail["kind"] == "schema"
assert detail["message"] == "invalid source_spec"
assert isinstance(detail["errors"], list)
```

- [ ] **Step 2: Run tests to verify they fail (red)**

```bash
uv run pytest tests/api/test_info_sources.py -v
```

Expected: failures at every newly-rewritten assertion.

- [ ] **Step 3: Migrate the route file**

Apply the seven rewrites above in `src/api/routes/info_sources.py`. Remove the now-unused `HTTPException` import if no other raises remain (there shouldn't be any). Add:

```python
from src.api.errors import FieldError, raise_422, raise_envelope
```

at the top with the other imports.

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/api/test_info_sources.py -v
```

Expected: green.

- [ ] **Step 5: Lint check**

```bash
uv run ruff check src/api/routes/info_sources.py
```

Expected: no findings (especially no B904 — every `raise_envelope` site that translates an exception passes `source_exc=e`).

- [ ] **Step 6: Commit**

```bash
git add src/api/routes/info_sources.py tests/api/test_info_sources.py
git commit -m "#15 refactor: info_sources routes use raise_envelope"
```

---

## Task 6: Migrate `src/api/routes/info_items.py`

**Files:**
- Modify: `src/api/routes/info_items.py` (~14 raise sites)
- Modify: `tests/api/test_info_items.py`, `tests/api/test_v2_endpoints.py`

Same playbook as Task 5. Map (line numbers are current at time of writing — confirm before editing):

| Lines | Current | Target |
|-------|---------|--------|
| 81-84 | 404 RepSpec not found by id | `raise_envelope(404, "lookup", f"RepSpec {assignment.rep_spec_id!r} not found")` |
| 91-99 | 422 `{message, errors}` for rep_fields | `raise_422(f"rep_fields does not satisfy RepSpec {assignment.rep_spec_id!r}", kind="domain", errors=errors, data={"rep_spec_id": str(assignment.rep_spec_id)})` |
| 109-112 | 422 invalid source_spec | `raise_422("invalid source_spec", kind="schema", errors=e.errors, source_exc=e)` |
| 113-121 | 409 duplicate | `raise_envelope(409, "conflict", "an InfoSource already exists for this URL", data={"url": e.url, "existing_info_source_id": str(e.existing_info_source_id)}, source_exc=e)` |
| 198 | 404 InfoItem | `raise_envelope(404, "lookup", "InfoItem not found")` |
| 224 | 404 InfoItem | same |
| 229 | 422 ULID malformed | `raise_envelope(422, "domain", "info_source_id is not a valid ULID", errors=[FieldError(path="/info_source_id", message="not a valid ULID", code="invalid_ulid")], source_exc=e)` |
| 233 | 404 InfoSource | `raise_envelope(404, "lookup", "InfoSource not found")` |
| 269, 274, 315, 320, 355, 386 | 422 ULID malformed (six sites) | analogous to line 229 — adjust `path` to the field name |
| 284 | 404 InfoItem | `raise_envelope(404, "lookup", "InfoItem not found", source_exc=e)` |
| 286 | 404 RepSpec | `raise_envelope(404, "lookup", "RepSpec not found", source_exc=e)` |
| 288-291 | 422 `{missing: ...}` | `raise_422("rep_fields incomplete", kind="domain", errors=[FieldError(path=m.get("path", ""), message=m.get("message", "missing"), code="rep_fields_incomplete") for m in e.missing], source_exc=e)` |
| 330, 332 | 404 not found (bind_revision) | `raise_envelope(404, "lookup", "InfoItem not found", source_exc=e)` and similar |
| 359 | 404 Assignment | `raise_envelope(404, "lookup", "Assignment not found")` |
| 390-393 | 404 with longer message | `raise_envelope(404, "lookup", "rep_spec_assignment not found for this info_item")` |

Note: `e.missing` in [assign_rep_spec.py:29-31](src/core/tools/assign_rep_spec.py#L29-L31) is a `list[dict]` already shaped roughly like `{path, message}`; preserve that shape into FieldError. If the dicts use a different key (`field` instead of `path`, etc.), check `tests/core/tools/test_assign_rep_spec.py` for examples.

- [ ] **Step 1: Update assertions in `tests/api/test_info_items.py`, `tests/api/test_v2_endpoints.py`, and `tests/api/test_create_info_item_atomic.py`**

Run:

```bash
rg -n '"detail"|json\(\)\[' tests/api/test_info_items.py tests/api/test_v2_endpoints.py tests/api/test_create_info_item_atomic.py
```

Walk each hit; rewrite per the patterns from Task 5. Pay particular attention to `test_create_info_item_atomic.py` around lines 203-205 — the 409 conflict shape moves `existing_info_source_id` and `url` under `detail["data"]`.

- [ ] **Step 2: Run tests (red)**

```bash
uv run pytest tests/api/test_info_items.py tests/api/test_v2_endpoints.py -v
```

Expected: failures across the touched assertions.

- [ ] **Step 3: Migrate the route file**

Apply all 14 rewrites. Add the import:

```python
from src.api.errors import FieldError, raise_422, raise_envelope
```

Remove `HTTPException` from the FastAPI import if no longer used.

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/api/test_info_items.py tests/api/test_v2_endpoints.py -v
```

Expected: green.

- [ ] **Step 5: Lint check**

```bash
uv run ruff check src/api/routes/info_items.py
```

Expected: no findings.

- [ ] **Step 6: Commit**

```bash
git add src/api/routes/info_items.py tests/api/test_info_items.py tests/api/test_v2_endpoints.py tests/api/test_create_info_item_atomic.py
git commit -m "#15 refactor: info_items routes use raise_envelope"
```

---

## Task 7: Migrate `src/api/routes/rep_specs.py`

**Files:**
- Modify: `src/api/routes/rep_specs.py` (2 raise sites; also strip the docstring `#15` note)
- Modify: `tests/api/test_rep_specs.py`

| Lines | Current | Target |
|-------|---------|--------|
| 55-59 | 422 `{message, errors}` for InvalidRepSpecError | `raise_422("invalid rep_spec", kind="schema", errors=e.errors, source_exc=e)` |
| 100 | 404 RepSpec not found | `raise_envelope(404, "lookup", "RepSpec not found")` |

Also: remove the `Error responses` block in the [POST /rep-specs docstring (line 35-49)](src/api/routes/rep_specs.py#L35-L49) — replace with a one-sentence reference to the unified envelope:

```text
Errors use the standard envelope (see ``src/api/errors.py``); ``kind`` is
``schema`` for envelope/sub-schema validation, ``body`` for Pydantic-level
issues.
```

If the route file has a `GET /rep-specs` paginated list route, check for any other 422 sites (e.g. malformed `provider` query param — currently handled by Pydantic so the global handler covers it).

- [ ] **Step 1: Rewrite assertions in `tests/api/test_rep_specs.py`** — same pattern as before.

- [ ] **Step 2: Run tests (red)**:

```bash
uv run pytest tests/api/test_rep_specs.py -v
```

- [ ] **Step 3: Migrate the route file + docstring fix.**

- [ ] **Step 4: Run tests**:

```bash
uv run pytest tests/api/test_rep_specs.py -v
```

Expected: green.

- [ ] **Step 5: Lint**:

```bash
uv run ruff check src/api/routes/rep_specs.py
```

- [ ] **Step 6: Commit**

```bash
git add src/api/routes/rep_specs.py tests/api/test_rep_specs.py
git commit -m "#15 refactor: rep_specs routes use raise_envelope; drop #15 docstring note"
```

---

## Task 8: Migrate `src/api/routes/source_revisions.py`

**Files:**
- Modify: `src/api/routes/source_revisions.py` (4 raise sites)
- Modify: `tests/api/test_source_revisions.py`

| Lines | Current | Target |
|-------|---------|--------|
| 43 | 422 ULID malformed | `raise_envelope(422, "domain", "info_source_id is not a valid ULID", errors=[FieldError(path="/info_source_id", message="not a valid ULID", code="invalid_ulid")], source_exc=e)` |
| 47 | 404 info_source | `raise_envelope(404, "lookup", "info_source not found")` |
| 122 | 422 ULID malformed (path-shape) | `raise_envelope(422, "domain", "source_revision_id is not a valid ULID", errors=[FieldError(path="/source_revision_id", message="not a valid ULID", code="invalid_ulid")], source_exc=e)` |
| 126 | 404 source_revision | `raise_envelope(404, "lookup", "source_revision not found")` |

- [ ] **Step 1: Rewrite test assertions.**
- [ ] **Step 2: Run tests (red).**
- [ ] **Step 3: Migrate route file.**
- [ ] **Step 4: Run tests (green).**
- [ ] **Step 5: Lint.**
- [ ] **Step 6: Commit**

```bash
git add src/api/routes/source_revisions.py tests/api/test_source_revisions.py
git commit -m "#15 refactor: source_revisions routes use raise_envelope"
```

---

## Task 9: Migrate `src/api/routes/tools.py`

**Files:**
- Modify: `src/api/routes/tools.py` (3 raise sites: 501 + two 422s in preview-extraction)
- Modify: `tests/api/test_tools_preview_extraction.py` (lines ~98-100 and ~115-116 assert `detail["error"] == "validation_failed"` / `"target_unreachable"` — the top-level `error` key vanishes; replace with `detail["kind"]` + `detail["errors"][0]["code"]` checks)
- Modify: `tests/api/test_tools_fetch_and_render.py` (line ~82 asserts `"Playwright" in response.json()["detail"]` — after migration `detail` is a dict, change to `"Playwright" in response.json()["detail"]["message"]`)
- Audit (grep first, may need no changes): `tests/api/test_tools_find.py`, `tests/api/test_tools_propose_selectors.py`, `tests/api/test_tools_validate.py`

There is **no** `tests/api/test_tools.py` — tool tests are split per-tool under `test_tools_<name>.py`.

| Lines | Current | Target |
|-------|---------|--------|
| 152 | 501 "Playwright fetcher not yet integrated (#3)" | `raise_envelope(501, "unimplemented", "Playwright fetcher not yet integrated (#3)")` |
| 185-192 | 422 `{error: "validation_failed", errors: ...}` (SourceSpecValidationError) | `raise_422("source_spec validation failed", kind="schema", errors=[FieldError(path=err["path"] or "", message=err["message"]) for err in e.errors] or [FieldError(path="", message=str(e))], source_exc=e)` |
| 194-197 | 422 `{error: "target_unreachable", message: str(e)}` (TargetUnreachableError) | `raise_422(str(e), kind="domain", errors=[FieldError(path="/target/url", message=str(e), code="target_unreachable")], source_exc=e)` |

Note: this is a contract change for `preview_extraction` — the old shape carried a top-level `error` discriminator (`"validation_failed"` vs `"target_unreachable"`). The new contract carries that information in `code` on the FieldError. Update the docstring accordingly.

- [ ] **Step 1: Rewrite test assertions in `test_tools_preview_extraction.py` and `test_tools_fetch_and_render.py`. Grep the other three `test_tools_*.py` files for `"detail"` and update any error-body assertions you find.**
- [ ] **Step 2: Run tests (red).**

```bash
uv run pytest tests/api/test_tools_preview_extraction.py tests/api/test_tools_fetch_and_render.py -v
```

- [ ] **Step 3: Migrate route file + docstring on `preview_extraction_route` (lines ~170-181).** Replace the "Returns 422 with structured errors on schema validation failure (`error: "validation_failed"`) or target unreachability (`error: "target_unreachable"`)." sentence with: "Returns 422 with the standard error envelope; ``code`` on each FieldError disambiguates (``target_unreachable``, etc.)."
- [ ] **Step 4: Run tests (green).**

```bash
uv run pytest tests/api/test_tools_preview_extraction.py tests/api/test_tools_fetch_and_render.py tests/api/test_tools_find.py tests/api/test_tools_propose_selectors.py tests/api/test_tools_validate.py -v
```

- [ ] **Step 5: Lint.**
- [ ] **Step 6: Commit**

```bash
git add src/api/routes/tools.py tests/api/test_tools_preview_extraction.py tests/api/test_tools_fetch_and_render.py
# add the other three test_tools_*.py if any were touched
git commit -m "#15 refactor: tools routes use raise_envelope"
```

---

## Task 10: Unify `ValidationErrorOut` with `FieldError`

**Files:**
- Modify: `src/api/schemas/tools.py`
- Modify: `src/api/routes/tools.py` (any explicit `ValidationErrorOut(...)` calls)

`ValidationErrorOut` in [schemas/tools.py:8-12](src/api/schemas/tools.py#L8-L12) is a `BaseModel` with `path` and `message` — the same fields as `FieldError` (minus `code`). Make them the same class so the OpenAPI schema has one entry and the SDK gets one `FieldError` model on both 200-success paths and 422-failure paths.

- [ ] **Step 1: Update test if any test specifically imports `ValidationErrorOut`**

```bash
rg -n "ValidationErrorOut" tests/
```

Adjust imports as needed (likely just rename to `FieldError`).

- [ ] **Step 2: Replace the class definition in `src/api/schemas/tools.py`**

Delete the `ValidationErrorOut` class and add at the top:

```python
from src.api.errors import FieldError as ValidationErrorOut
```

(Re-export for backward compat inside the codebase; existing call sites continue to work.) Or, more aggressively, do a rename — change all six `ValidationErrorOut(...)` constructor calls and the three `list[ValidationErrorOut]` annotations to `FieldError`. Rename is cleaner; pick that unless it's painful.

- [ ] **Step 3: Run the full suite**

```bash
uv run pytest -q
```

Expected: green.

- [ ] **Step 4: Lint**

```bash
uv run ruff check src/api/schemas/tools.py src/api/routes/tools.py
```

- [ ] **Step 5: Commit**

```bash
git add src/api/schemas/tools.py src/api/routes/tools.py   # + any test files touched
git commit -m "#15 refactor: alias ValidationErrorOut to FieldError (single source of truth)"
```

---

## Task 11: Declare ErrorEnvelope as the default 4xx/5xx response on the v1 router

**Files:**
- Modify: `src/api/main.py`

So that `openapi-python-client` generates a single named `ErrorEnvelope` Pydantic model on the SDK side instead of one anonymous schema per route.

- [ ] **Step 1: Add `responses=` to the v1 router**

In `src/api/main.py`, the `v1_router` is currently:

```python
v1_router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_api_key)])
```

Change to:

```python
from src.api.errors import ErrorEnvelope

class EnvelopeResponse(BaseModel):
    """Outer ``{"detail": ErrorEnvelope}`` wrapper for OpenAPI docs.

    Public name (no leading underscore) so ``openapi-python-client`` generates a
    cleanly-named SDK model — the class name is what surfaces in
    ``components/schemas`` and feeds the SDK code generator.
    """
    detail: ErrorEnvelope

v1_router = APIRouter(
    prefix="/api/v1",
    dependencies=[Depends(require_api_key)],
    responses={
        400: {"model": EnvelopeResponse, "description": "Bad request (envelope)."},
        401: {"model": EnvelopeResponse, "description": "Auth required (envelope)."},
        403: {"model": EnvelopeResponse, "description": "Forbidden (envelope)."},
        404: {"model": EnvelopeResponse, "description": "Not found (envelope)."},
        409: {"model": EnvelopeResponse, "description": "Conflict (envelope)."},
        422: {"model": EnvelopeResponse, "description": "Validation failed (envelope)."},
        500: {"model": EnvelopeResponse, "description": "Internal error (envelope)."},
    },
)
```

Add `from pydantic import BaseModel` if not already imported.

- [ ] **Step 2: Dump the OpenAPI schema and inspect it**

```bash
uv run python scripts/dump_openapi.py > /tmp/openapi.json
python -c "import json; s = json.load(open('/tmp/openapi.json')); print(sorted(s['components']['schemas'].keys()))" | tr ',' '\n' | grep -i 'error\|envelope\|field'
```

Expected: at least `ErrorEnvelope` and `FieldError` appear in `components/schemas`.

- [ ] **Step 3: Verify the suite still passes**

```bash
uv run pytest -q
```

- [ ] **Step 4: Commit**

```bash
git add src/api/main.py
git commit -m "#15 feat: declare ErrorEnvelope as default 4xx/5xx response model on /api/v1"
```

---

## Task 12: SDK — typed envelope attrs on `error_from_response`

**Files:**
- Modify: `clients/python/src/archiver_client/errors.py`
- Modify: `clients/python/tests/test_errors.py`
- Modify: `clients/python/tests/test_client.py` (and other respx-mock tests that simulate 4xx bodies)

After this task, every `InformationError` subclass surfaces `.kind`, `.message`, `.errors: list[dict]`, `.data: dict | None` parsed from the envelope. We do **not** add a fallback parser — pre-prod, no legacy bodies in flight.

- [ ] **Step 1: Write failing tests in `clients/python/tests/test_errors.py`**

Replace (or augment — preserve the class-mapping tests) the existing file:

```python
"""Direct unit tests for error_from_response parsing + status → exception mapping."""

from __future__ import annotations

import json

from archiver_client.errors import (
    AuthError,
    InformationError,
    NotFound,
    ServerError,
    ValidationError,
    error_from_response,
)


def _envelope(kind: str, message: str, errors=None, data=None) -> bytes:
    body = {"kind": kind, "message": message, "errors": errors or []}
    if data is not None:
        body["data"] = data
    return json.dumps({"detail": body}).encode("utf-8")


def test_404_envelope_populates_typed_attrs():
    err = error_from_response(404, _envelope("lookup", "InfoItem not found"))
    assert isinstance(err, NotFound)
    assert err.status_code == 404
    assert err.kind == "lookup"
    assert err.message == "InfoItem not found"
    assert err.errors == []
    assert err.data is None


def test_422_schema_envelope_populates_errors():
    body = _envelope(
        "schema",
        "invalid rep_spec",
        errors=[{"path": "/document/provider", "message": "missing", "code": "required"}],
    )
    err = error_from_response(422, body)
    assert isinstance(err, ValidationError)
    assert err.kind == "schema"
    assert len(err.errors) == 1
    assert err.errors[0]["path"] == "/document/provider"


def test_409_conflict_envelope_populates_data():
    body = _envelope(
        "conflict",
        "duplicate",
        data={"existing_info_source_id": "01HXX..."},
    )
    err = error_from_response(409, body)
    assert isinstance(err, InformationError)   # 409 maps to base class (or Conflict subclass if added)
    assert err.kind == "conflict"
    assert err.data == {"existing_info_source_id": "01HXX..."}


def test_500_envelope():
    body = _envelope("server", "internal server error")
    err = error_from_response(500, body)
    assert isinstance(err, ServerError)
    assert err.kind == "server"


def test_401_envelope():
    body = _envelope("auth", "Invalid API key")
    err = error_from_response(401, body)
    assert isinstance(err, AuthError)
    assert err.kind == "auth"


def test_malformed_envelope_falls_back_to_unknown_kind():
    """Defensive: a body that doesn't match the envelope shape gets kind='unknown'."""
    err = error_from_response(500, b"not json at all")
    assert isinstance(err, ServerError)
    assert err.kind == "unknown"
    assert err.message  # something non-empty


def test_body_attr_still_populated_for_debugging():
    body = _envelope("lookup", "x")
    err = error_from_response(404, body)
    assert isinstance(err.body, str)
    assert "lookup" in err.body
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd clients/python && uv run pytest tests/test_errors.py -v
```

Expected: AttributeError on `.kind` / `.message` / `.errors` / `.data`.

- [ ] **Step 3: Implement**

Rewrite `clients/python/src/archiver_client/errors.py`:

```python
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


class ServerError(InformationError):
    """5xx from the Archiver service."""


def _parse_envelope(body_text: str) -> tuple[str, str, list[dict[str, Any]], dict[str, Any] | None]:
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

    common = dict(
        status_code=status, body=body_text, kind=kind, errors=errors, data=data
    )

    if status in (401, 403):
        return AuthError(message, **common)
    if status == 404:
        return NotFound(message, **common)
    if status == 422:
        return ValidationError(message, **common)
    if 500 <= status < 600:
        return ServerError(message, **common)
    return InformationError(message, **common)
```

- [ ] **Step 4: Run tests**

```bash
cd clients/python && uv run pytest tests/test_errors.py -v
```

Expected: green.

- [ ] **Step 5: Audit `clients/python/tests/test_client.py`**

```bash
rg -n '"detail"' clients/python/tests/test_client.py
```

Every respx mock that simulates a 4xx/5xx body needs to return the envelope shape. Update each.

The known offender from the issue is `test_get_info_item_422_raises_validation_error` (around line 183) — replace its mock body with `{"detail": {"kind": "domain", "message": "info_item_id is not a valid ULID", "errors": [{"path": "/info_item_id", "message": "not a valid ULID"}]}}`.

- [ ] **Step 6: Run all SDK tests**

```bash
cd clients/python && uv run pytest -q
```

Expected: green.

- [ ] **Step 7: Commit**

```bash
git add clients/python/src/archiver_client/errors.py clients/python/tests/test_errors.py clients/python/tests/test_client.py
git commit -m "#15 feat(sdk): parse error envelope into typed attrs (.kind, .errors, .data); v2.0 break"
```

---

## Task 13: Regenerate SDK + bump version + README

**Files:**
- Regenerate: `clients/python/src/archiver_client/generated/**`
- Modify: `clients/python/pyproject.toml`
- Modify: `clients/python/README.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Regenerate**

```bash
bash clients/python/scripts/regen.sh
```

Expected last line: `Regenerated: /home/exedev/archiver/clients/python/src/archiver_client/generated`.

- [ ] **Step 2: Verify named ErrorEnvelope + FieldError appear in the generated models**

```bash
ls clients/python/src/archiver_client/generated/models/ | grep -i 'envelope\|field_error'
```

Expected: at least `error_envelope.py` and `field_error.py` (filenames may vary by openapi-python-client's slugifier — should be one each, named).

- [ ] **Step 3: Run SDK tests**

```bash
cd clients/python && uv run pytest -q
```

Expected: green. If the generated `Response` classes for individual routes now point at the new envelope type, generated-test assertions may need a touch-up.

- [ ] **Step 4: Bump version**

Edit `clients/python/pyproject.toml`: change `version = "1.3.X"` (whatever it currently is) to `version = "2.0.0"`.

- [ ] **Step 5: Update `clients/python/README.md`**

Find the "SDK version history" section (mirrors what's in `CLAUDE.md`). Add an entry:

```markdown
- **v2.0** (breaking) — all error response bodies now use a unified envelope
  shape (`{detail: {kind, message, errors[], data}}`). `InformationError`
  subclasses surface `.kind`, `.message`, `.errors`, `.data` parsed from the
  envelope. See archiver#15.
```

- [ ] **Step 6: Update `CLAUDE.md`**

In the Conventions section, after the "Translated exceptions chain via …" bullet, add a new "Error envelope" sub-section:

```markdown
**Error envelope:** Every non-2xx response uses one shape, defined by
`ErrorEnvelope` in `src/api/errors.py`:

​```json
{"detail": {"kind": "lookup", "message": "...", "errors": [...], "data": {...}}}
​```

Routes raise via `raise_envelope(status, kind, message, ...)` or `raise_422(...)`
(in `src/api/errors.py`), never via `HTTPException` directly. The global
exception handlers in `register_error_handlers(app)` wrap any FastAPI-raised
HTTPException (unmatched route 404, 405) or uncaught Exception (500) into the
envelope. See archiver#15.
```

Also, in the "SDK version history" line, update `v1.3` → `v1.3 added /rep-specs ... v2.0 was a breaking change that introduced the unified error envelope.`

- [ ] **Step 7: Run the FULL repo test suite**

```bash
uv run pytest -q
uv run ruff check .
```

Both green.

- [ ] **Step 8: Commit**

```bash
git add clients/python/ CLAUDE.md
git commit -m "#15 chore: regen SDK, bump to v2.0.0, document envelope in CLAUDE.md + SDK README"
```

---

## Task 14: Smoke against dev server

**Files:** none (just verification).

- [ ] **Step 1: Start the dev server on 8021**

> **Historical.** The `uvicorn` invocation below predates `scripts/dev_server.sh` and pointed at the **production** database (2026-07-18 incident). Do not copy it; use `bash scripts/dev_server.sh`.

```bash
export $(cat /etc/archiver/.env .env 2>/dev/null | xargs)
uv run uvicorn src.api.main:app --host 0.0.0.0 --port 8021 --reload &
```

- [ ] **Step 2: Run the existing smoke**

```bash
bash scripts/smoke_phase4.sh
```

Expected: all steps pass (it exercises 2xx paths only, so the envelope change should be invisible to it).

- [ ] **Step 3: Manual envelope spot-check**

```bash
# 404 envelope
curl -s -H "X-API-Key: $ARCHIVER_API_KEY" http://localhost:8021/api/v1/info-items/01HXXXXXXXXXXXXXXXXXXXXXXX | python -m json.tool

# 401 envelope (no key)
curl -s http://localhost:8021/api/v1/info-items/01HXXXXXXXXXXXXXXXXXXXXXXX | python -m json.tool

# 422 Pydantic (bad body)
curl -s -X POST -H "X-API-Key: $ARCHIVER_API_KEY" -H "content-type: application/json" \
  -d '{}' http://localhost:8021/api/v1/info-items | python -m json.tool

# 422 schema (bad rep_spec doc)
curl -s -X POST -H "X-API-Key: $ARCHIVER_API_KEY" -H "content-type: application/json" \
  -d '{"provider": "gcs", "name": "x", "document": {}}' http://localhost:8021/api/v1/rep-specs | python -m json.tool

# 404 unmatched route (FastAPI-raised, must still be enveloped)
curl -s -H "X-API-Key: $ARCHIVER_API_KEY" http://localhost:8021/api/v1/nope | python -m json.tool

# 405 wrong method
curl -s -X DELETE -H "X-API-Key: $ARCHIVER_API_KEY" http://localhost:8021/api/v1/info-items | python -m json.tool
```

Each response body must be shaped `{"detail": {"kind": "<kind>", "message": "...", "errors": [...], "data": {...optional...}}}`.

- [ ] **Step 4: Tear down**

```bash
pkill -f "uvicorn src.api.main"
```

- [ ] **Step 5: Commit (if anything needed fixing during smoke)**

Only if Step 3 surfaced a route the migration missed. Otherwise skip.

---

## Task 15: PR creation

After the worktree's branch passes `uv run pytest -q` and `uv run ruff check .` clean:

- [ ] **Step 1: Push the branch**

```bash
git push -u origin issue-15-normalize-error-envelopes
```

- [ ] **Step 2: Open the PR**

Use the `superpowers:shipping-work-claude` skill, or directly:

```bash
gh pr create --title "#15 feat: normalize error response envelopes" --body "$(cat <<'EOF'
## Summary
- Introduces unified ``ErrorEnvelope`` model for every non-2xx response.
- Adds ``raise_envelope`` / ``raise_422`` helpers + three global exception handlers.
- Migrates all route raise sites to the envelope.
- SDK v2.0 (breaking): ``InformationError`` subclasses surface ``.kind``, ``.message``, ``.errors``, ``.data``.

Closes #15.

## Test plan
- [ ] ``uv run pytest`` passes
- [ ] ``uv run ruff check .`` clean
- [ ] ``bash scripts/smoke_phase4.sh`` passes against dev server (port 8021)
- [ ] Manual curl spot-checks of 401/404/405/422/500 all return envelope shape

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: After merge to `main`**

```bash
sudo systemctl restart archiver
sudo journalctl -u archiver -n 50
```

Confirm clean startup logs ("Outbox publisher started" or "ARCHIVER_REDIS_URL not set — outbox publisher disabled").

---

## Out of scope (do not pull into this PR)

- Adding a `Conflict` subclass to the SDK (current `InformationError` base class is sufficient; the typed attrs already let callers branch on `.kind == "conflict"`).
- Restructuring 200 responses for `/tools/validate-*` (the 200-shape with `valid: bool, errors: list` stays — distinct contract from error responses).
- Changes to `/health` or `/openapi.json` — both stay outside the envelope.
- Localization of `message` — single string in English for now.
- Rich-text in `message` (no markdown, no HTML).

Anything beyond the above belongs in a separate issue and a separate PR.

---

## Notes for the agent executing this plan

- **Read CLAUDE.md.** Especially the TDD section and the `raise ... from e` chaining rule.
- **Trust the global handler.** Once Task 3 lands, *every* unmigrated `HTTPException(detail="bare string")` site is silently wrapped. You won't see immediate breakage in production code; you'll see test assertion drift. That is the load-bearing observation that makes Tasks 4–9 feasible incrementally.
- **Commits are cheap.** Each task is one commit. If you find yourself making a commit that combines, say, Task 5 *and* Task 6, split before pushing.
- **Don't skip the lint step.** Ruff B904 is enforced in CI; the helper supports `source_exc=` precisely so every translated exception keeps its `__cause__`. Forgetting to pass it will fail CI loud.
- **If a route already raised the right shape** (the typed-error envelope was already `{message, errors}`), the test diff for that site will be small — only adding the `kind` assertion. Don't over-rewrite.
- **Pagination param errors** (limit/offset out of range) are Pydantic-handled — the global handler covers them automatically, no route-side changes needed.
