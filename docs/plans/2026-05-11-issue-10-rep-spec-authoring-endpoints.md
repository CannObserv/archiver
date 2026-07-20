# Issue #10 — RepSpec Authoring Endpoints Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `POST /api/v1/rep-specs`, `GET /api/v1/rep-specs`, `GET /api/v1/rep-specs/{id}` plus an `ArchiverClient.create_rep_spec` / `get_rep_spec` / `list_rep_specs` SDK wrapper, so operators (and the Phase 6 Replicator smoke) can author RepSpecs without a direct psql INSERT.

**Architecture:** Mirror the existing `POST /info-sources` pattern verbatim — dedicated route module, dedicated Pydantic schemas, a core tool encapsulating validation + persistence, a serializer helper, and an ergonomic SDK wrapper layered over the regenerated openapi-python-client output. Reuse `validate_rep_spec` (envelope + per-provider sub-schema). `schema_version` is server-defaulted to `1`; the request body is just `{provider, name, document}`. No PATCH/DELETE — RepSpecs are immutable post-create (author a new one + reassign for changes). No `(provider, name)` uniqueness constraint — operator-managed for now. List endpoint returns the v1.2 `Page[RepSpecOut]` envelope with `?provider=` filter and the `limit+1` `has_more` probe.

**Tech Stack:** FastAPI, SQLAlchemy 2.x async, Pydantic v2, pytest + pytest-asyncio, jsonschema (existing validator), openapi-python-client (SDK regen), Postgres (existing `information.rep_specs` table — no migration required, table already shipped in Phase 4).

---

## Pre-flight context for the implementer

You are working in the `archiver` FastAPI service. Before touching code:

- Read [CLAUDE.md](../../CLAUDE.md) — house rules (TDD, commit conventions, schema/route patterns, `B904` exception-chaining lint rule).
- Read the existing `POST /info-sources` flow end-to-end — it is the template for everything below:
  - [src/api/routes/info_sources.py](../../src/api/routes/info_sources.py)
  - [src/api/schemas/info_source.py](../../src/api/schemas/info_source.py)
  - [src/core/tools/create_info_source.py](../../src/core/tools/create_info_source.py)
  - [src/api/serializers.py](../../src/api/serializers.py) (specifically `info_source_to_out`)
  - [tests/api/test_info_sources.py](../../tests/api/test_info_sources.py)
- The `RepSpec` ORM model is [src/core/models/rep_spec.py](../../src/core/models/rep_spec.py) — primary key is `rep_spec_id`, not `id`. Fields: `rep_spec_id`, `provider`, `name`, `schema_version`, `document` (JSONB), `created_at`. No unique constraint on `(provider, name)`; no need to add one.
- The validator is [src/core/rep_spec_schema/validator.py](../../src/core/rep_spec_schema/validator.py) — `validate_rep_spec(doc) -> (ok, errors)` where each error is `{"path": "...", "message": "..."}`.
- The list pagination envelope is `Page[ItemT]` from [src/api/schemas/pagination.py](../../src/api/schemas/pagination.py).
- App composition + auth dependency: [src/api/main.py](../../src/api/main.py) (look at `v1_router.include_router(...)`).
- All routes inside `/api/v1` already gate on `X-API-Key` via the router-level dependency; you do not add auth code per route.

**Environment:**

```bash
export $(cat /etc/archiver/.env .env 2>/dev/null | xargs)
```

**Pre-task sanity check:**

```bash
uv run pytest tests/api -q
uv run ruff check . && uv run ruff format --check .
```

Expected: green. If not, fix existing breakage before continuing.

---

## File map

| Path | Action | Responsibility |
|---|---|---|
| `src/api/schemas/rep_spec.py` | Create | `RepSpecCreate` (request body) + `RepSpecOut` (response body). |
| `src/core/tools/create_rep_spec.py` | Create | `create_rep_spec(db, *, provider, name, document)` core tool. Validates via `validate_rep_spec`; raises `InvalidRepSpecError(errors=[...])`. Caller commits. |
| `src/api/serializers.py` | Modify | Add `rep_spec_to_out(spec: RepSpec) -> RepSpecOut`. Add `RepSpec` to ORM-import block, `RepSpecOut` to schema-import block. |
| `src/api/routes/rep_specs.py` | Create | `POST /rep-specs`, `GET /rep-specs`, `GET /rep-specs/{rep_spec_id}`. Mirrors `info_sources.py`. |
| `src/api/main.py` | Modify | Register the new router on `v1_router`. |
| `tests/core/tools/test_create_rep_spec.py` | Create | Unit tests for the core tool (happy path + each validation failure mode). |
| `tests/api/test_rep_specs.py` | Create | HTTP behavior — 201 happy path, 422 (bad envelope / bad provider / bad sub-schema), 404 on GET, list filtering + pagination. |
| `clients/python/src/archiver_client/generated/**` | Regenerate | Run `clients/python/scripts/regen.sh`. Don't hand-edit. |
| `clients/python/src/archiver_client/client.py` | Modify | Add three async methods: `create_rep_spec`, `get_rep_spec`, `list_rep_specs`. |
| `clients/python/src/archiver_client/__init__.py` | Modify | Export `RepSpecOut`, `PageRepSpecOut`. Bump `__version__` to `"1.3.0"`. |
| `clients/python/pyproject.toml` | Modify | Bump `version` to `1.3.0`. |
| `clients/python/README.md` | Modify | Note v1.3 adds RepSpec authoring. |
| `scripts/smoke_phase4.sh` | Modify | Replace step 10's psql INSERT with `POST /api/v1/rep-specs`. Keep psql cleanup (no DELETE endpoint). |
| `CLAUDE.md` | Modify | Add the three new endpoints to the mutating-endpoints table. Remove the "#10 / no `POST /rep-specs`" bullet from "Known v1 gaps". |

**Out of scope (do not implement):**
- `PATCH /rep-specs/{id}` or `DELETE /rep-specs/{id}` — explicit immutability.
- `(provider, name)` uniqueness constraint or 409 handling.
- A `Page[RepSpecOut]` SDK wrapper for filter-by-name; only `?provider=` is supported.

---

## Task 1: Add Pydantic IO schemas for RepSpec endpoints

**Files:**
- Create: `src/api/schemas/rep_spec.py`

- [ ] **Step 1: Write the failing test**

Create `tests/api/schemas/test_rep_spec.py` (mkdir `tests/api/schemas/` + `__init__.py` if needed):

```python
"""Schema-level tests for RepSpecCreate/RepSpecOut."""

import pytest
from pydantic import ValidationError

from src.api.schemas.rep_spec import RepSpecCreate, RepSpecOut


def _gcs_doc() -> dict:
    return {
        "provider": "gcs",
        "credentials_alias": "gcs-prod",
        "path_template": "archive/{info_item.slug}/{source_revision.date}.html",
        "required_fields": ["info_item.slug", "source_revision.date"],
        "object_options": {"storage_class": "STANDARD"},
    }


def test_rep_spec_create_accepts_minimum_fields():
    body = RepSpecCreate(provider="gcs", name="board-meetings-gcs", document=_gcs_doc())
    assert body.provider == "gcs"
    assert body.name == "board-meetings-gcs"
    assert body.document["provider"] == "gcs"


def test_rep_spec_create_forbids_extra_fields():
    with pytest.raises(ValidationError):
        RepSpecCreate(
            provider="gcs",
            name="x",
            document=_gcs_doc(),
            schema_version=1,  # type: ignore[call-arg]  -- intentionally extra
        )


def test_rep_spec_create_rejects_empty_name():
    with pytest.raises(ValidationError):
        RepSpecCreate(provider="gcs", name="", document=_gcs_doc())


def test_rep_spec_out_round_trip():
    out = RepSpecOut(
        rep_spec_id="01J0000000000000000000000A",
        provider="gcs",
        name="x",
        schema_version=1,
        document=_gcs_doc(),
        created_at="2026-05-11T00:00:00Z",  # pydantic accepts ISO 8601
    )
    assert out.provider == "gcs"
```

- [ ] **Step 2: Run test, verify it fails**

```bash
uv run pytest tests/api/schemas/test_rep_spec.py -v
```

Expected: `ModuleNotFoundError: No module named 'src.api.schemas.rep_spec'`.

- [ ] **Step 3: Implement the schemas**

Create `src/api/schemas/rep_spec.py`:

```python
"""Pydantic IO schemas for top-level /rep-specs endpoints.

RepSpecs are immutable post-create: the API exposes POST/GET only, no
PATCH/DELETE. Operators reassign a new RepSpec to evolve provider config.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class RepSpecCreate(BaseModel):
    """Request body for POST /rep-specs.

    ``schema_version`` is server-defaulted to 1 — only v1 exists today, so
    accepting a client-supplied value would be ceremony. Bump the server
    default (and add a discriminator) once a v2 envelope ships.
    """

    model_config = {"extra": "forbid"}

    provider: str = Field(
        min_length=1,
        max_length=50,
        description="Provider key (e.g. 'gcs', 'gdrive', 'ia'). Validated via validate_rep_spec.",
    )
    name: str = Field(
        min_length=1,
        max_length=200,
        description="Operator-friendly label for this RepSpec. Not unique by design.",
    )
    document: dict[str, Any] = Field(
        description=(
            "RepSpec envelope document. Validated against rep_spec_schema/v1.json + "
            "the per-provider sub-schema at rep_spec_schema/providers/{provider}/v1.json."
        ),
    )


class RepSpecOut(BaseModel):
    """Projection of a rep_specs row."""

    rep_spec_id: str
    provider: str
    name: str
    schema_version: int
    document: dict[str, Any]
    created_at: datetime
```

- [ ] **Step 4: Run tests, verify pass**

```bash
uv run pytest tests/api/schemas/test_rep_spec.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add tests/api/schemas/__init__.py tests/api/schemas/test_rep_spec.py src/api/schemas/rep_spec.py
git commit -m "#10 feat: add RepSpecCreate/RepSpecOut Pydantic schemas"
```

(`tests/api/schemas/__init__.py` may already exist; if it does, skip the `git add` on it.)

---

## Task 2: Core tool — `create_rep_spec` + `InvalidRepSpecError`

**Files:**
- Create: `src/core/tools/create_rep_spec.py`
- Create: `tests/core/tools/test_create_rep_spec.py`

This is the persistence + validation core. The route handler calls into this and translates the typed error to 422. Mirrors the shape of `create_info_source`.

- [ ] **Step 1: Write the failing tests**

Create `tests/core/tools/test_create_rep_spec.py`:

```python
"""Tests for the create_rep_spec core tool."""

from __future__ import annotations

import pytest

from src.core.models import RepSpec
from src.core.tools.create_rep_spec import (
    InvalidRepSpecError,
    create_rep_spec,
)


def _gcs_doc() -> dict:
    return {
        "provider": "gcs",
        "credentials_alias": "gcs-prod",
        "path_template": "archive/{info_item.slug}/{source_revision.date}.html",
        "required_fields": ["info_item.slug", "source_revision.date"],
        "object_options": {"storage_class": "STANDARD"},
    }


@pytest.mark.asyncio
async def test_create_rep_spec_persists_row_with_schema_version_1(session):
    spec = await create_rep_spec(
        session, provider="gcs", name="board-meetings-gcs", document=_gcs_doc()
    )
    await session.commit()

    fetched = await session.get(RepSpec, spec.rep_spec_id)
    assert fetched is not None
    assert fetched.provider == "gcs"
    assert fetched.name == "board-meetings-gcs"
    assert fetched.schema_version == 1
    assert fetched.document["path_template"].startswith("archive/")


@pytest.mark.asyncio
async def test_create_rep_spec_rejects_missing_envelope_field(session):
    bad = _gcs_doc()
    del bad["path_template"]
    with pytest.raises(InvalidRepSpecError) as exc:
        await create_rep_spec(session, provider="gcs", name="x", document=bad)
    assert any("path_template" in e["message"] for e in exc.value.errors)


@pytest.mark.asyncio
async def test_create_rep_spec_rejects_unknown_provider(session):
    bad = _gcs_doc() | {"provider": "s3"}
    with pytest.raises(InvalidRepSpecError) as exc:
        await create_rep_spec(session, provider="s3", name="x", document=bad)
    assert any("provider" in e["path"] for e in exc.value.errors)


@pytest.mark.asyncio
async def test_create_rep_spec_rejects_invalid_provider_sub_schema(session):
    bad = _gcs_doc()
    bad["object_options"] = {"storage_class": "BANANA"}
    with pytest.raises(InvalidRepSpecError) as exc:
        await create_rep_spec(session, provider="gcs", name="x", document=bad)
    assert any("object_options" in e["path"] for e in exc.value.errors)


@pytest.mark.asyncio
async def test_create_rep_spec_provider_mismatch_with_document_is_rejected(session):
    """If the request says provider=gcs but the document says provider=gdrive, reject."""
    bad = _gcs_doc() | {"provider": "gdrive"}
    with pytest.raises(InvalidRepSpecError):
        await create_rep_spec(session, provider="gcs", name="x", document=bad)
```

The mismatch test pins the design: `provider` is stored on the column AND inside `document`, so they must agree. The core tool enforces this; you'll add the check in the implementation.

- [ ] **Step 2: Run tests, verify they fail**

```bash
uv run pytest tests/core/tools/test_create_rep_spec.py -v
```

Expected: `ModuleNotFoundError` / 5 failures.

- [ ] **Step 3: Implement the core tool**

Create `src/core/tools/create_rep_spec.py`:

```python
"""create_rep_spec — author a new RepSpec row.

Validates the envelope + provider sub-schema, enforces that the request-level
``provider`` matches the embedded document's provider, and persists the row at
schema_version=1. Caller is responsible for committing the session.

RepSpecs are immutable once written; there is no update or delete path. To
evolve provider config, author a new RepSpec and reassign affected InfoItems.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.models import RepSpec
from src.core.rep_spec_schema.validator import ValidationError, validate_rep_spec

CURRENT_SCHEMA_VERSION = 1


class CreateRepSpecError(Exception):
    """Base class for create_rep_spec failures."""


class InvalidRepSpecError(CreateRepSpecError):
    """The submitted document failed envelope or provider sub-schema validation."""

    def __init__(self, errors: list[ValidationError]) -> None:
        self.errors = errors
        super().__init__(f"invalid rep_spec: {errors}")


async def create_rep_spec(
    db: AsyncSession,
    *,
    provider: str,
    name: str,
    document: dict,
) -> RepSpec:
    """Persist a new RepSpec row and return it.

    The document is validated against the v1 envelope and the per-provider
    sub-schema. If ``document['provider']`` disagrees with the request-level
    ``provider`` argument, the call is rejected — the two are redundant by
    design, and storing a disagreement would corrupt the index.
    """
    errors: list[ValidationError] = []

    doc_provider = document.get("provider")
    if doc_provider is not None and doc_provider != provider:
        errors.append(
            {
                "path": "/provider",
                "message": (
                    f"request provider {provider!r} disagrees with "
                    f"document.provider {doc_provider!r}"
                ),
            }
        )

    ok, schema_errors = validate_rep_spec(document)
    if not ok:
        errors.extend(schema_errors)

    if errors:
        raise InvalidRepSpecError(errors)

    spec = RepSpec(
        provider=provider,
        name=name,
        schema_version=CURRENT_SCHEMA_VERSION,
        document=document,
    )
    db.add(spec)
    await db.flush()
    return spec
```

- [ ] **Step 4: Run tests, verify pass**

```bash
uv run pytest tests/core/tools/test_create_rep_spec.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add tests/core/tools/test_create_rep_spec.py src/core/tools/create_rep_spec.py
git commit -m "#10 feat: add create_rep_spec core tool + InvalidRepSpecError"
```

---

## Task 3: Serializer + route module + router registration

**Files:**
- Modify: `src/api/serializers.py`
- Create: `src/api/routes/rep_specs.py`
- Modify: `src/api/main.py`
- Create: `tests/api/test_rep_specs.py`

- [ ] **Step 1: Write the failing HTTP tests**

Create `tests/api/test_rep_specs.py`:

```python
"""Tests for top-level /rep-specs endpoints.

Covers:
- POST /rep-specs (201 happy path + 422 validation failures)
- GET /rep-specs/{rep_spec_id} (200 + 404)
- GET /rep-specs (Page envelope, ?provider= filter, pagination probe)
"""

from __future__ import annotations

import pytest

HEADERS = {"X-API-Key": "test-secret-key"}


@pytest.fixture(autouse=True)
def _set_api_key(monkeypatch):
    monkeypatch.setenv("ARCHIVER_API_KEY", "test-secret-key")


def _gcs_doc() -> dict:
    return {
        "provider": "gcs",
        "credentials_alias": "gcs-prod",
        "path_template": "archive/{info_item.slug}/{source_revision.date}.html",
        "required_fields": ["info_item.slug", "source_revision.date"],
        "object_options": {"storage_class": "STANDARD"},
    }


def _gdrive_doc() -> dict:
    return {
        "provider": "gdrive",
        "credentials_alias": "gdrive-prod",
        "path_template": "{info_item.slug}",
        "required_fields": ["info_item.slug"],
        "object_options": {},
    }


# ---------------------------------------------------------------------------
# POST /api/v1/rep-specs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_returns_201_with_server_assigned_id_and_schema_version(client):
    resp = await client.post(
        "/api/v1/rep-specs",
        headers=HEADERS,
        json={"provider": "gcs", "name": "board-meetings", "document": _gcs_doc()},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert len(body["rep_spec_id"]) == 26
    assert body["provider"] == "gcs"
    assert body["name"] == "board-meetings"
    assert body["schema_version"] == 1
    assert body["document"]["path_template"].startswith("archive/")


@pytest.mark.asyncio
async def test_post_returns_422_on_missing_envelope_field(client):
    bad = _gcs_doc()
    del bad["path_template"]
    resp = await client.post(
        "/api/v1/rep-specs",
        headers=HEADERS,
        json={"provider": "gcs", "name": "x", "document": bad},
    )
    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert body["detail"]["message"] == "invalid rep_spec"
    assert any("path_template" in e["message"] for e in body["detail"]["errors"])


@pytest.mark.asyncio
async def test_post_returns_422_on_unknown_provider(client):
    bad = _gcs_doc() | {"provider": "s3"}
    resp = await client.post(
        "/api/v1/rep-specs",
        headers=HEADERS,
        json={"provider": "s3", "name": "x", "document": bad},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_post_returns_422_on_bad_provider_sub_schema(client):
    bad = _gcs_doc()
    bad["object_options"] = {"storage_class": "BANANA"}
    resp = await client.post(
        "/api/v1/rep-specs",
        headers=HEADERS,
        json={"provider": "gcs", "name": "x", "document": bad},
    )
    assert resp.status_code == 422
    body = resp.json()
    assert any("object_options" in e["path"] for e in body["detail"]["errors"])


@pytest.mark.asyncio
async def test_post_returns_422_on_provider_mismatch(client):
    bad = _gdrive_doc()  # document says gdrive
    resp = await client.post(
        "/api/v1/rep-specs",
        headers=HEADERS,
        json={"provider": "gcs", "name": "x", "document": bad},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_post_rejects_extra_fields(client):
    resp = await client.post(
        "/api/v1/rep-specs",
        headers=HEADERS,
        json={
            "provider": "gcs",
            "name": "x",
            "document": _gcs_doc(),
            "schema_version": 1,  # forbidden
        },
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/rep-specs/{rep_spec_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_returns_200_for_existing(client):
    created = (
        await client.post(
            "/api/v1/rep-specs",
            headers=HEADERS,
            json={"provider": "gcs", "name": "n", "document": _gcs_doc()},
        )
    ).json()
    resp = await client.get(
        f"/api/v1/rep-specs/{created['rep_spec_id']}", headers=HEADERS
    )
    assert resp.status_code == 200
    assert resp.json()["rep_spec_id"] == created["rep_spec_id"]


@pytest.mark.asyncio
async def test_get_returns_404_for_unknown_id(client):
    resp = await client.get(
        "/api/v1/rep-specs/01J0000000000000000000000Z", headers=HEADERS
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_returns_422_for_malformed_ulid(client):
    resp = await client.get("/api/v1/rep-specs/not-a-ulid", headers=HEADERS)
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/rep-specs (list)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_returns_page_envelope(client):
    for i in range(3):
        await client.post(
            "/api/v1/rep-specs",
            headers=HEADERS,
            json={"provider": "gcs", "name": f"n{i}", "document": _gcs_doc()},
        )
    resp = await client.get("/api/v1/rep-specs", headers=HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"items", "has_more", "limit", "offset"}
    assert body["limit"] == 100
    assert body["offset"] == 0
    assert body["has_more"] is False
    assert len(body["items"]) >= 3


@pytest.mark.asyncio
async def test_list_filters_by_provider(client):
    await client.post(
        "/api/v1/rep-specs",
        headers=HEADERS,
        json={"provider": "gcs", "name": "n-gcs", "document": _gcs_doc()},
    )
    await client.post(
        "/api/v1/rep-specs",
        headers=HEADERS,
        json={"provider": "gdrive", "name": "n-gd", "document": _gdrive_doc()},
    )
    resp = await client.get("/api/v1/rep-specs?provider=gdrive", headers=HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert all(item["provider"] == "gdrive" for item in body["items"])


@pytest.mark.asyncio
async def test_list_pagination_has_more_flips_at_limit(client):
    for i in range(3):
        await client.post(
            "/api/v1/rep-specs",
            headers=HEADERS,
            json={"provider": "gcs", "name": f"p{i}", "document": _gcs_doc()},
        )
    resp = await client.get("/api/v1/rep-specs?limit=2&offset=0", headers=HEADERS)
    body = resp.json()
    assert len(body["items"]) == 2
    assert body["has_more"] is True

    resp2 = await client.get("/api/v1/rep-specs?limit=2&offset=2", headers=HEADERS)
    body2 = resp2.json()
    assert body2["has_more"] is False


@pytest.mark.asyncio
async def test_list_requires_api_key(client):
    resp = await client.get("/api/v1/rep-specs")  # no headers
    assert resp.status_code in (401, 403)
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
uv run pytest tests/api/test_rep_specs.py -v
```

Expected: 404s (router not mounted) or import errors.

- [ ] **Step 3: Add the serializer**

Edit `src/api/serializers.py`. Add `RepSpec` to the `from src.core.models import (...)` block, and `RepSpecOut` to the `from src.api.schemas.rep_spec import ...` block (new import). Then append:

```python
def rep_spec_to_out(spec: RepSpec) -> RepSpecOut:
    """Serialise a RepSpec ORM row."""
    return RepSpecOut(
        rep_spec_id=str(spec.rep_spec_id),
        provider=spec.provider,
        name=spec.name,
        schema_version=spec.schema_version,
        document=spec.document,
        created_at=spec.created_at,
    )
```

- [ ] **Step 4: Implement the route module**

Create `src/api/routes/rep_specs.py`:

```python
"""Top-level RepSpec endpoints.

POST/GET only — RepSpecs are immutable once written. To change provider
config, author a new RepSpec and reassign affected InfoItems via the existing
``POST /info-items/{id}/rep-spec-assignments`` flow.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.api.deps import get_db_session
from src.api.schemas.pagination import Page
from src.api.schemas.rep_spec import RepSpecCreate, RepSpecOut
from src.api.schemas.types import ULIDStr
from src.api.serializers import rep_spec_to_out
from src.core.models import RepSpec
from src.core.tools.create_rep_spec import InvalidRepSpecError, create_rep_spec

router = APIRouter(prefix="/rep-specs", tags=["rep-specs"])


@router.post("", response_model=RepSpecOut, status_code=201)
async def create_rep_spec_route(
    body: RepSpecCreate,
    session: AsyncSession = Depends(get_db_session),
) -> RepSpecOut:
    """Author a new RepSpec.

    ``schema_version`` is server-defaulted to 1. The ``document`` field is
    validated against the v1 envelope and the matching per-provider
    sub-schema. ``body.provider`` and ``document['provider']`` must agree.

    Error responses:
    - 422: document fails envelope or provider sub-schema validation, or the
           request-level ``provider`` disagrees with ``document.provider``.
    """
    try:
        spec = await create_rep_spec(
            session,
            provider=body.provider,
            name=body.name,
            document=body.document,
        )
    except InvalidRepSpecError as e:
        raise HTTPException(
            status_code=422,
            detail={"message": "invalid rep_spec", "errors": e.errors},
        ) from e

    await session.commit()
    await session.refresh(spec)
    return rep_spec_to_out(spec)


@router.get("", response_model=Page[RepSpecOut])
async def list_rep_specs(
    provider: str | None = Query(default=None, max_length=50),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db_session),
) -> Page[RepSpecOut]:
    """List RepSpecs with offset pagination, optionally filtered by provider.

    ``has_more`` is derived via a ``limit+1`` probe; no total count is computed.
    Ordering is stable on ``(created_at, rep_spec_id)``.
    """
    stmt = select(RepSpec).order_by(RepSpec.created_at, RepSpec.rep_spec_id)
    if provider is not None:
        stmt = stmt.where(RepSpec.provider == provider)
    stmt = stmt.offset(offset).limit(limit + 1)
    rows = (await session.execute(stmt)).scalars().all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    return Page[RepSpecOut](
        items=[rep_spec_to_out(s) for s in rows],
        has_more=has_more,
        limit=limit,
        offset=offset,
    )


@router.get("/{rep_spec_id}", response_model=RepSpecOut)
async def get_rep_spec(
    rep_spec_id: ULIDStr,
    session: AsyncSession = Depends(get_db_session),
) -> RepSpecOut:
    """Fetch a single RepSpec by ID."""
    spec = await session.get(RepSpec, ULID.from_str(rep_spec_id))
    if spec is None:
        raise HTTPException(status_code=404, detail="RepSpec not found")
    return rep_spec_to_out(spec)
```

- [ ] **Step 5: Register the router**

Edit `src/api/main.py`. Add the import alongside the existing route imports:

```python
from src.api.routes.rep_specs import router as rep_specs_router
```

And register on `v1_router` (slot it between `info_sources_router` and `source_revisions_router` — keep it alphabetical-ish):

```python
v1_router.include_router(info_items_router)
v1_router.include_router(info_sources_router)
v1_router.include_router(rep_specs_router)
v1_router.include_router(source_revisions_router)
v1_router.include_router(tools_router)
```

- [ ] **Step 6: Run tests, verify pass**

```bash
uv run pytest tests/api/test_rep_specs.py -v
uv run pytest tests/api -q   # confirm no regressions
```

Expected: all `test_rep_specs.py` tests pass; the full `tests/api` suite stays green.

- [ ] **Step 7: Lint**

```bash
uv run ruff check . && uv run ruff format .
```

- [ ] **Step 8: Commit**

```bash
git add src/api/serializers.py src/api/routes/rep_specs.py src/api/main.py tests/api/test_rep_specs.py
git commit -m "#10 feat: POST/GET /rep-specs with Page envelope + provider filter"
```

---

## Task 4: Regenerate the SDK + add hand-written wrappers

**Files:**
- Regenerate: `clients/python/src/archiver_client/generated/**`
- Modify: `clients/python/src/archiver_client/client.py`
- Modify: `clients/python/src/archiver_client/__init__.py`
- Modify: `clients/python/pyproject.toml`
- Modify: `clients/python/README.md`
- Create: `clients/python/tests/test_rep_spec_methods.py`

- [ ] **Step 1: Regenerate the SDK from the new OpenAPI schema**

Run the existing regen script (creates a tmp OpenAPI dump from the live `app`, then runs `openapi-python-client`):

```bash
bash clients/python/scripts/regen.sh
```

Expected last line: `Regenerated: /home/exedev/archiver/clients/python/src/archiver_client/generated`.

Sanity-check that the new rep-specs module exists:

```bash
ls clients/python/src/archiver_client/generated/api/rep_specs/
```

Expected: at least `create_rep_spec_route_api_v1_rep_specs_post.py`, `get_rep_spec_api_v1_rep_specs_rep_spec_id_get.py`, `list_rep_specs_api_v1_rep_specs_get.py` (names follow the operation_id convention).

If filenames differ, adjust the imports in the next step accordingly.

- [ ] **Step 2: Write the failing SDK wrapper tests**

Create `clients/python/tests/test_rep_spec_methods.py`. Match the existing `respx` style (see `clients/python/tests/test_client.py`) — `with respx.mock:` context, `httpx.Response(...)` for the canned reply, and the shared `client` fixture from `clients/python/tests/conftest.py` (already pointed at `BASE_URL = "http://archiver.test"`, `API_KEY = "test-key"`):

```python
"""respx-mocked tests for ArchiverClient.{create,get,list}_rep_spec wrappers."""

import httpx
import pytest
import respx

BASE_URL = "http://archiver.test"
_TS = "2026-05-11T00:00:00Z"


def _gcs_doc() -> dict:
    return {
        "provider": "gcs",
        "credentials_alias": "gcs-prod",
        "path_template": "archive/{info_item.slug}/{source_revision.date}.html",
        "required_fields": ["info_item.slug", "source_revision.date"],
        "object_options": {"storage_class": "STANDARD"},
    }


def _rep_spec_payload(rep_spec_id: str = "01HZZ00000000000000000000R") -> dict:
    return {
        "rep_spec_id": rep_spec_id,
        "provider": "gcs",
        "name": "x",
        "schema_version": 1,
        "document": _gcs_doc(),
        "created_at": _TS,
    }


@pytest.mark.asyncio
async def test_create_rep_spec(client):
    with respx.mock:
        respx.post(f"{BASE_URL}/api/v1/rep-specs").mock(
            return_value=httpx.Response(201, json=_rep_spec_payload())
        )
        out = await client.create_rep_spec(provider="gcs", name="x", document=_gcs_doc())
    assert out.provider == "gcs"
    assert out.schema_version == 1


@pytest.mark.asyncio
async def test_get_rep_spec(client):
    rid = "01HZZ00000000000000000000R"
    with respx.mock:
        respx.get(f"{BASE_URL}/api/v1/rep-specs/{rid}").mock(
            return_value=httpx.Response(200, json=_rep_spec_payload(rid))
        )
        out = await client.get_rep_spec(rid)
    assert str(out.rep_spec_id) == rid


@pytest.mark.asyncio
async def test_list_rep_specs_with_provider_filter(client):
    with respx.mock:
        respx.get(f"{BASE_URL}/api/v1/rep-specs").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [_rep_spec_payload()],
                    "has_more": False,
                    "limit": 10,
                    "offset": 0,
                },
            )
        )
        page = await client.list_rep_specs(provider="gcs", limit=10, offset=0)
    assert page.has_more is False
    assert page.limit == 10
    assert len(page.items) == 1
```

Run from the SDK package:

```bash
cd clients/python && uv run pytest tests/test_rep_spec_methods.py -v
```

Expected: fail (no wrappers yet — `AttributeError` on `client.create_rep_spec`).

- [ ] **Step 3: Add the wrappers to `client.py`**

**First, discover the generated module + model names.** openapi-python-client derives names from the FastAPI operation_id (route function name) and from inferred sub-models for JSONB fields; for the `document: dict[str, Any]` field on `RepSpecCreate`, precedent (`InfoSourceCreateSourceSpec`, `InfoItemCreateInitialSourceSpecType0`) says the generator may emit either `RepSpecCreateDocument` or `RepSpecCreateDocumentType0`. Confirm before importing:

```bash
ls clients/python/src/archiver_client/generated/api/rep_specs/
ls clients/python/src/archiver_client/generated/models/ | grep -i rep_spec
```

Use whatever the generator actually emitted in the imports below.

Slot the new methods near the existing RepSpec assignment block (after `set_public_url`, around line 250-ish). Pattern follows `create_info_source` / `get_info_source` / `list_info_sources` verbatim.

```python
# Imports — add to the appropriate import groups at the top of the file.
# (Replace each module name with the regen-emitted name verified in the `ls` above.)
from archiver_client.generated.api.rep_specs import (
    create_rep_spec_route_api_v1_rep_specs_post as _create_rep_spec,
)
from archiver_client.generated.api.rep_specs import (
    get_rep_spec_api_v1_rep_specs_rep_spec_id_get as _get_rep_spec,
)
from archiver_client.generated.api.rep_specs import (
    list_rep_specs_api_v1_rep_specs_get as _list_rep_specs,
)
from archiver_client.generated.models.page_rep_spec_out import PageRepSpecOut
from archiver_client.generated.models.rep_spec_create import RepSpecCreate
from archiver_client.generated.models.rep_spec_create_document import RepSpecCreateDocument
from archiver_client.generated.models.rep_spec_out import RepSpecOut
```

```python
# --- RepSpec endpoints ---

async def create_rep_spec(
    self,
    *,
    provider: str,
    name: str,
    document: dict,
) -> RepSpecOut:
    """Author a new RepSpec.

    Validates against the v1 envelope + per-provider sub-schema server-side.
    Raises ``ValidationError`` if either fails. Returns the persisted row.
    """
    body = RepSpecCreate(
        provider=provider,
        name=name,
        document=RepSpecCreateDocument.from_dict(document),
    )
    response = await _create_rep_spec.asyncio_detailed(client=self._gen_client, body=body)
    return _unwrap(response)


async def get_rep_spec(self, rep_spec_id: str) -> RepSpecOut:
    """Fetch a single RepSpec by ID."""
    response = await _get_rep_spec.asyncio_detailed(
        client=self._gen_client, rep_spec_id=rep_spec_id
    )
    return _unwrap(response)


async def list_rep_specs(
    self,
    *,
    provider: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> PageRepSpecOut:
    """List RepSpecs as a paginated envelope.

    ``provider`` restricts to a single provider key. ``limit``/``offset`` are
    forwarded when set; omit to accept server defaults (limit=100, offset=0).
    Server caps ``limit`` at 500.
    """
    response = await _list_rep_specs.asyncio_detailed(
        client=self._gen_client,
        provider=provider if provider is not None else UNSET,
        limit=UNSET if limit is None else limit,
        offset=UNSET if offset is None else offset,
    )
    return _unwrap(response)
```

- [ ] **Step 4: Export the new model + bump version**

Edit `clients/python/src/archiver_client/__init__.py`:

```python
from archiver_client.generated.models.rep_spec_out import RepSpecOut
from archiver_client.generated.models.page_rep_spec_out import PageRepSpecOut
```

Add `"RepSpecOut"` and `"PageRepSpecOut"` to `__all__`. Bump `__version__ = "1.3.0"`.

Edit `clients/python/pyproject.toml`:

```toml
version = "1.3.0"
```

(Currently `1.2.0` per the file; the `__init__.py` was already drifted at `1.1.0` — this bump realigns both at `1.3.0`.)

Edit `clients/python/README.md` — update the version note line:

```
Currently at **v1.3** (adds RepSpec authoring — `create_rep_spec`,
`get_rep_spec`, `list_rep_specs`; backwards compatible with v1.2).
```

- [ ] **Step 5: Run tests, verify pass**

```bash
cd clients/python && uv run pytest -q
```

Expected: full SDK suite green, including the three new tests.

- [ ] **Step 6: Lint**

```bash
cd /home/exedev/archiver && uv run ruff check . && uv run ruff format .
```

- [ ] **Step 7: Commit**

```bash
git add clients/python/src/archiver_client/generated \
        clients/python/src/archiver_client/client.py \
        clients/python/src/archiver_client/__init__.py \
        clients/python/pyproject.toml \
        clients/python/README.md \
        clients/python/tests/test_rep_spec_methods.py
git commit -m "#10 feat(sdk): v1.3 — add create_rep_spec/get_rep_spec/list_rep_specs"
```

---

## Task 5: Update the Phase 4 smoke script

**Files:**
- Modify: `scripts/smoke_phase4.sh`

The smoke script currently shells out to `psql` for step 10 because the endpoint did not exist. Replace that with `curl POST /api/v1/rep-specs`. Keep the psql `DELETE` in cleanup — there is no DELETE endpoint.

- [ ] **Step 1: Read the current step 10 + cleanup block**

```bash
grep -n "Step 10\|step 10\|INSERT INTO information.rep_specs\|DELETE FROM information.rep_specs" scripts/smoke_phase4.sh
```

Confirm line numbers before editing.

- [ ] **Step 2: Replace step 10 with the HTTP call**

The replacement block calls the new endpoint, extracts `rep_spec_id` from the response, and updates the step's header comment. Use the same `call POST ...` helper the script already uses for steps 6/7/11. Pattern from step 11:

```bash
step 10 "POST /rep-specs (create RepSpec via new endpoint)"
RESP=$(call POST /api/v1/rep-specs \
    "{\"provider\": \"gcs\", \"name\": \"smoke-gcs-$$\", \"document\": $REP_SPEC_DOC}")
REP_SPEC_ID=$(echo "$RESP" | jq -r .rep_spec_id)
assert_nonempty "$REP_SPEC_ID" "rep_spec_id"
echo "  ok (rep_spec_id=$REP_SPEC_ID)"
```

Also update the header comment block at the top of the file:

```
# 10.  POST /rep-specs → 201, capture rep_spec_id
```

(Replacing the line that previously said `# 10.  Insert RepSpec via psql — no POST /rep-specs endpoint; direct DB insert`.)

- [ ] **Step 3: Run the smoke script against the dev server**

If the dev server isn't already running on port 8021:

> **Historical.** The `uvicorn` invocation below predates `scripts/dev_server.sh` and pointed at the **production** database (2026-07-18 incident). Do not copy it; use `bash scripts/dev_server.sh`.

```bash
export $(cat /etc/archiver/.env .env 2>/dev/null | xargs)
uv run uvicorn src.api.main:app --host 0.0.0.0 --port 8021 --reload &
sleep 2
```

Then run smoke:

```bash
bash scripts/smoke_phase4.sh
```

Expected: all steps print `ok`; final summary prints `rep_spec_id=...`.

Kill the dev server when done:

```bash
pkill -f "uvicorn src.api.main:app.*8021"
```

- [ ] **Step 4: Commit**

```bash
git add scripts/smoke_phase4.sh
git commit -m "#10 chore: smoke step 10 uses POST /rep-specs instead of psql INSERT"
```

---

## Task 6: Update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

Two edits:

1. In the "**Mutating endpoints:**" table, add three rows (slot them next to the other rep-spec rows, around the existing `Assign a RepSpec` line):

| Endpoint | HTTP | SDK method |
|---|---|---|
| Author a RepSpec | `POST /rep-specs` | `create_rep_spec(provider, name, document)` |
| Get a RepSpec | `GET /rep-specs/{id}` | `get_rep_spec(id)` |
| List RepSpecs (filter by provider, paginated) | `GET /rep-specs?provider=…&limit=&offset=` | `list_rep_specs(provider=None, limit=None, offset=None)` |

Note in the row description (or as a follow-on sentence in the pagination paragraph) that `GET /rep-specs` also uses the v1.2 `Page` envelope.

2. In the "**Known v1 gaps**" subsection, **remove** the bullet:

```
- No `POST /rep-specs` — RepSpecs must be inserted out-of-band (`psql`); see #10. Phase 6 prereq.
```

3. In the pagination paragraph (`**Pagination (v1.2):**` line), update the list of routes to include `/rep-specs`:

```
**Pagination (v1.2+):** `GET /info-items`, `GET /info-sources`, and `GET /rep-specs` return a `Page` envelope...
```

- [ ] **Step 1: Make the edits**

Use `Edit` to apply each change. Verify the resulting Markdown table is well-formed (no stray pipes).

- [ ] **Step 2: Verify reads cleanly**

```bash
grep -A 1 "Author a RepSpec\|Known v1 gaps" CLAUDE.md
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "#10 docs: CLAUDE.md — note POST/GET /rep-specs + remove gap bullet"
```

---

## Final verification

Before opening the PR, run the full guardrail sweep from the repo root:

- [ ] **Step 1: Tests**

```bash
uv run pytest -q
```

Expected: green.

- [ ] **Step 2: Lint**

```bash
uv run ruff check . && uv run ruff format --check .
```

Expected: green.

- [ ] **Step 3: SDK tests** (separate environment)

```bash
cd clients/python && uv run pytest -q && cd -
```

Expected: green.

- [ ] **Step 4: OpenAPI diff sanity check**

```bash
uv run python scripts/dump_openapi.py | jq '.paths | keys[] | select(. | startswith("/api/v1/rep-specs"))'
```

Expected output (three lines):

```
"/api/v1/rep-specs"
"/api/v1/rep-specs/{rep_spec_id}"
```

(Two strings — the second covers both GET-by-id and any other path-id ops.)

- [ ] **Step 5: Manual probe against the dev server** (optional, but recommended before merging)

Restart `archiver` if testing on 8020, or relaunch the dev uvicorn on 8021. Then:

```bash
curl -sS -X POST "http://127.0.0.1:8021/api/v1/rep-specs" \
  -H "X-API-Key: $ARCHIVER_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"provider":"gcs","name":"manual-probe","document":{"provider":"gcs","credentials_alias":"x","path_template":"x","required_fields":["a.b"],"object_options":{}}}' \
  | jq .
```

Expected: 201 response with `rep_spec_id`, `schema_version: 1`, etc.

- [ ] **Step 6: Open the PR via `gh pr create`**

Title: `#10 feat: POST /rep-specs + SDK v1.3 for RepSpec authoring`

PR body: link the issue (`Closes #10`), summarize the three endpoints, note SDK bump, note smoke script update, note CLAUDE.md cleanup, note immutability / no-uniqueness decisions.

---

## Reference: what we deliberately did NOT do

These come up naturally in review — call them out in the PR description so the reviewer can stet quickly:

- **No PATCH/DELETE on `/rep-specs`.** RepSpecs are immutable post-create. To evolve config, author a new RepSpec and reassign.
- **No `(provider, name)` uniqueness constraint.** Operators may dedup themselves; one-line migration to add later if needed.
- **No 409 on duplicate name** — follows from the above.
- **No client-supplied `schema_version`.** Only v1 exists; server defaults the column to 1. Revisit when v2 envelope ships.
- **No filter besides `?provider=`.** No `?name~=` substring filter, no full-text search — there are far fewer RepSpecs than InfoItems, and the SDK list pulls work fine.
