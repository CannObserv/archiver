"""Top-level InfoSource endpoints.

Distinct from the sub-resource binding endpoint
``POST /info-items/{id}/info-sources`` (which binds an existing InfoSource to
an InfoItem). These routes author and read InfoSource rows directly — used by
Watcher Phase 5 for fragment authoring under a shared root.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.api.deps import get_db_session
from src.api.schemas.info_source import InfoSourceCreate, InfoSourceOut
from src.api.schemas.types import ULIDStr
from src.api.serializers import info_source_to_out
from src.core.models import InfoSource
from src.core.tools.create_info_source import (
    DuplicateUrlError,
    InvalidSourceSpecError,
    ParentMustBeRootError,
    ParentNotFoundError,
    create_info_source,
)

router = APIRouter(prefix="/info-sources", tags=["info-sources"])


@router.post("", response_model=InfoSourceOut, status_code=201)
async def create_info_source_route(
    body: InfoSourceCreate,
    session: AsyncSession = Depends(get_db_session),
) -> InfoSourceOut:
    """Create a new InfoSource (root or fragment).

    A root source is created when ``parent_info_source_id`` is omitted; the
    submitted ``source_spec`` must carry ``target.url``. A fragment is created
    when ``parent_info_source_id`` is supplied; the spec must NOT carry
    ``target.url`` and the parent must itself be a root.

    Error responses:
    - 422: source_spec fails schema/shape validation, or
           ``parent_info_source_id`` is supplied but points at another fragment,
           or the path-shape ULID is malformed.
    - 404: ``parent_info_source_id`` references no existing InfoSource.
    - 409: a root with the same canonicalized URL already exists. The response
           body's ``existing_info_source_id`` is the row the operator should
           bind to instead.
    """
    parent_ulid: ULID | None = None
    if body.parent_info_source_id is not None:
        try:
            parent_ulid = ULID.from_str(body.parent_info_source_id)
        except ValueError:
            raise HTTPException(status_code=422, detail="parent_info_source_id is not a valid ULID")

    try:
        src = await create_info_source(
            session,
            source_spec=body.source_spec,
            parent_info_source_id=parent_ulid,
        )
    except InvalidSourceSpecError as e:
        raise HTTPException(
            status_code=422,
            detail={"message": "invalid source_spec", "errors": e.errors},
        )
    except ParentNotFoundError:
        raise HTTPException(status_code=404, detail="parent InfoSource not found")
    except ParentMustBeRootError:
        raise HTTPException(
            status_code=422,
            detail="parent_info_source_id must reference a root InfoSource",
        )
    except DuplicateUrlError as e:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "an InfoSource already exists for this URL",
                "url": e.url,
                "existing_info_source_id": str(e.existing_info_source_id),
            },
        )

    await session.commit()
    await session.refresh(src)
    return info_source_to_out(src)


@router.get("", response_model=list[InfoSourceOut])
async def list_info_sources(
    parent_info_source_id: str | None = Query(default=None),
    session: AsyncSession = Depends(get_db_session),
) -> list[InfoSourceOut]:
    """List InfoSources, optionally filtered to fragments under a parent.

    Without ``parent_info_source_id`` returns all rows. With it, returns only
    fragments whose ``parent_info_source_id`` matches.
    """
    stmt = select(InfoSource).order_by(InfoSource.created_at)
    if parent_info_source_id is not None:
        try:
            parent_ulid = ULID.from_str(parent_info_source_id)
        except ValueError:
            raise HTTPException(status_code=422, detail="parent_info_source_id is not a valid ULID")
        stmt = stmt.where(InfoSource.parent_info_source_id == parent_ulid)
    rows = (await session.execute(stmt)).scalars().all()
    return [info_source_to_out(s) for s in rows]


@router.get("/{info_source_id}", response_model=InfoSourceOut)
async def get_info_source(
    info_source_id: ULIDStr,
    session: AsyncSession = Depends(get_db_session),
) -> InfoSourceOut:
    """Fetch a single InfoSource by ID."""
    src = await session.get(InfoSource, ULID.from_str(info_source_id))
    if src is None:
        raise HTTPException(status_code=404, detail="InfoSource not found")
    return info_source_to_out(src)
