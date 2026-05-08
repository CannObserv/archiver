"""POST /source-revisions and PATCH /source-revisions/{id} route handlers."""

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.api.deps import get_db_session
from src.api.schemas.source_revision import (
    SourceRevisionCachePatch,
    SourceRevisionCreate,
    SourceRevisionOut,
)
from src.api.serializers import source_revision_to_out
from src.core.models import InfoSource, SourceRevision

router = APIRouter(prefix="/source-revisions", tags=["source-revisions"])


@router.post("", response_model=SourceRevisionOut, status_code=201)
async def create_source_revision(
    body: SourceRevisionCreate,
    response: Response,
    session: AsyncSession = Depends(get_db_session),
) -> SourceRevisionOut:
    """Create or return an existing SourceRevision.

    Idempotent on ``(info_source_id, content_fingerprint)``. Returns **201**
    on insert; **200** when the exact pair already exists.

    Raises:
        404: ``info_source_id`` does not reference a known InfoSource.
        422: ``content_fingerprint`` fails regex validation (Pydantic layer).
    """
    # --- Validate info_source_id references an existing InfoSource ---
    try:
        source_ulid = ULID.from_str(body.info_source_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="info_source_id is not a valid ULID")

    source = await session.get(InfoSource, source_ulid)
    if source is None:
        raise HTTPException(status_code=404, detail="info_source not found")

    # --- Upsert via INSERT … ON CONFLICT DO NOTHING … RETURNING ---
    stmt = (
        pg_insert(SourceRevision)
        .values(
            info_source_id=source_ulid,
            content_fingerprint=body.content_fingerprint,
            captured_at=body.captured_at,
            content_size_bytes=body.content_size_bytes,
            content_media_type=body.content_media_type,
            content_cache_uri=body.content_cache_uri,
            content_cache_expires_at=body.content_cache_expires_at,
        )
        .on_conflict_do_nothing(
            index_elements=["info_source_id", "content_fingerprint"]
        )
        .returning(SourceRevision)
    )
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()

    if row is None:
        # Idempotent no-op — fetch the existing row
        existing = await session.execute(
            select(SourceRevision).where(
                SourceRevision.info_source_id == source_ulid,
                SourceRevision.content_fingerprint == body.content_fingerprint,
            )
        )
        row = existing.scalar_one()
        response.status_code = status.HTTP_200_OK
    else:
        response.status_code = status.HTTP_201_CREATED

    await session.commit()
    return source_revision_to_out(row)


@router.patch("/{source_revision_id}", response_model=SourceRevisionOut)
async def patch_source_revision(
    source_revision_id: str,
    body: SourceRevisionCachePatch,
    session: AsyncSession = Depends(get_db_session),
) -> SourceRevisionOut:
    """Partially update cache fields on an existing SourceRevision.

    Only fields present in the request body are applied; omitted fields are
    left untouched.  Sending ``null`` explicitly clears the field.

    Raises:
        404: ``source_revision_id`` does not reference a known SourceRevision.
        422: ``source_revision_id`` is not a valid ULID.
    """
    try:
        rev_ulid = ULID.from_str(source_revision_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="source_revision_id is not a valid ULID")

    rev = await session.get(SourceRevision, rev_ulid)
    if rev is None:
        raise HTTPException(status_code=404, detail="source_revision not found")

    updates = body.model_dump(exclude_unset=True)
    for k, v in updates.items():
        setattr(rev, k, v)

    await session.commit()
    await session.refresh(rev)
    return source_revision_to_out(rev)
