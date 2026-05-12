"""Top-level RepSpec endpoints.

POST/GET only — RepSpecs are immutable once written. To change provider
config, author a new RepSpec and reassign affected InfoItems via the existing
``POST /info-items/{id}/rep-spec-assignments`` flow.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.api.deps import get_db_session
from src.api.errors import raise_422, raise_envelope
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
        raise_envelope(404, "lookup", "RepSpec not found")
    return rep_spec_to_out(spec)
