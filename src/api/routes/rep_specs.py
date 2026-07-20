"""Top-level RepSpec endpoints.

RepSpecs follow a *tiered* mutability contract (archiver#83; see
docs/plans/2026-07-20-83-rep-spec-document-editing-adr.md):

- ``name`` is always editable — a label with no replication semantics.
- ``document`` is editable only while the RepSpec is a **draft**: zero
  ``info_item_rep_specs`` rows, active or deactivated.
- Once assigned, the document is frozen. Author a replacement RepSpec and
  reassign affected InfoItems via ``POST /info-items/{id}/rep-spec-assignments``.
  A first-class clone + migrate flow is archiver#95.
- ``provider`` is frozen in every tier. There is no DELETE.

The freeze exists because ``InfoItemRepSpec`` is effective-dated: an assignment
row asserts which document produced the artefact at its ``public_url``, and an
in-place rewrite would make that unverifiable.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.api.deps import get_db_session
from src.api.errors import raise_422, raise_envelope
from src.api.schemas.pagination import Page
from src.api.schemas.rep_spec import RepSpecCreate, RepSpecOut, RepSpecPatch
from src.api.schemas.types import ULIDStr
from src.api.serializers import rep_spec_to_out
from src.core.models import RepSpec
from src.core.tools.create_rep_spec import InvalidRepSpecError, create_rep_spec
from src.core.tools.update_rep_spec import (
    InvalidRepSpecError as UpdateInvalidRepSpecError,
)
from src.core.tools.update_rep_spec import (
    RepSpecNotDraftError,
    RepSpecNotFoundError,
    update_rep_spec,
)

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

    Errors use the standard envelope (see ``src/api/errors.py``); ``kind`` is
    ``schema`` for envelope/sub-schema validation, ``body`` for Pydantic-level
    issues.
    """
    try:
        spec = await create_rep_spec(
            session,
            provider=body.provider,
            name=body.name,
            document=body.document,
        )
    except InvalidRepSpecError as e:
        raise_422("invalid rep_spec", kind="schema", errors=e.errors, source_exc=e)

    await session.commit()
    await session.refresh(spec)
    return rep_spec_to_out(spec)


@router.get("", response_model=Page[RepSpecOut])
async def list_rep_specs(
    provider: str | None = Query(default=None, min_length=1, max_length=50),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0, le=2**63 - 1),
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
        raise_envelope(404, "lookup", "RepSpec not found")
    return rep_spec_to_out(spec)


@router.patch("/{rep_spec_id}", response_model=RepSpecOut)
async def patch_rep_spec(
    rep_spec_id: ULIDStr,
    body: RepSpecPatch,
    session: AsyncSession = Depends(get_db_session),
) -> RepSpecOut:
    """Update a RepSpec's name and/or document under the tiered contract.

    ``name`` is accepted regardless of assignment state. ``document`` is a
    whole-document replacement accepted only while the RepSpec is a draft.
    Omitting both fields is a no-op and does not stamp ``updated_at``.

    Error responses:
    - 404 ``lookup``: RepSpec not found
    - 409 ``conflict``: document edit on an assigned RepSpec; ``data.assignment_count``
      carries the number of assignment rows (active + deactivated) blocking it
    - 422 ``schema``: document failed validation, or attempted a provider change
    """
    try:
        spec = await update_rep_spec(
            session,
            rep_spec_id=ULID.from_str(rep_spec_id),
            name=body.name,
            document=body.document,
        )
    except RepSpecNotFoundError as e:
        raise_envelope(404, "lookup", "RepSpec not found", source_exc=e)
    except RepSpecNotDraftError as e:
        raise_envelope(
            409,
            "conflict",
            "RepSpec document is frozen once assigned",
            data={
                "rep_spec_id": str(e.rep_spec_id),
                "assignment_count": e.assignment_count,
            },
            source_exc=e,
        )
    except UpdateInvalidRepSpecError as e:
        raise_422("invalid rep_spec", kind="schema", errors=e.errors, source_exc=e)

    await session.commit()
    await session.refresh(spec)
    return rep_spec_to_out(spec)
