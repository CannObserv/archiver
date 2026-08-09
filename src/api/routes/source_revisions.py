"""POST /source-revisions and PATCH /source-revisions/{id} route handlers."""

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.api.deps import get_db_session
from src.api.errors import FieldError, raise_envelope
from src.api.schemas.source_revision import (
    SourceRevisionCachePatch,
    SourceRevisionCreate,
    SourceRevisionOut,
)
from src.api.serializers import source_revision_to_out
from src.core.models import SourceRevision
from src.core.services.source_revision import (
    RevisionFacts,
    SourceRevisionIdConflictError,
    UnknownInfoSourceError,
    record_revision,
)

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
    except ValueError as e:
        raise_envelope(
            422,
            "domain",
            "info_source_id is not a valid ULID",
            errors=[
                FieldError(path="/info_source_id", message="not a valid ULID", code="invalid_ulid")
            ],
            source_exc=e,
        )

    # --- Validate optional client-supplied source_revision_id ---
    rev_ulid: ULID | None = None
    if body.source_revision_id is not None:
        try:
            rev_ulid = ULID.from_str(body.source_revision_id)
        except ValueError as e:
            raise_envelope(
                422,
                "domain",
                "source_revision_id is not a valid ULID",
                errors=[
                    FieldError(
                        path="/source_revision_id",
                        message="not a valid ULID",
                        code="invalid_ulid",
                    )
                ],
                source_exc=e,
            )

    # --- The write itself lives in the service layer (archiver#139) ---
    # Shared verbatim with the content.revisions consumer, so the
    # source_revision_captured payload this path emits and the one the bus path
    # emits are the same code rather than two implementations kept in step.
    try:
        row, inserted = await record_revision(
            session,
            RevisionFacts(
                info_source_id=source_ulid,
                content_fingerprint=body.content_fingerprint,
                captured_at=body.captured_at,
                content_size_bytes=body.content_size_bytes,
                content_media_type=body.content_media_type,
                content_cache_uri=body.content_cache_uri,
                content_cache_expires_at=body.content_cache_expires_at,
                source_revision_id=rev_ulid,
            ),
        )
    except UnknownInfoSourceError as e:
        raise_envelope(404, "lookup", "info_source not found", source_exc=e)
    except SourceRevisionIdConflictError as e:
        raise_envelope(
            409,
            "conflict",
            str(e),
            data={
                "existing_info_source_id": str(e.existing.info_source_id),
                "existing_content_fingerprint": e.existing.content_fingerprint,
            },
            source_exc=e,
        )

    response.status_code = status.HTTP_201_CREATED if inserted else status.HTTP_200_OK
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
    except ValueError as e:
        raise_envelope(
            422,
            "domain",
            "source_revision_id is not a valid ULID",
            errors=[
                FieldError(
                    path="/source_revision_id", message="not a valid ULID", code="invalid_ulid"
                )
            ],
            source_exc=e,
        )

    rev = await session.get(SourceRevision, rev_ulid)
    if rev is None:
        raise_envelope(404, "lookup", "source_revision not found")

    updates = body.model_dump(exclude_unset=True)
    for k, v in updates.items():
        setattr(rev, k, v)

    await session.commit()
    await session.refresh(rev)
    return source_revision_to_out(rev)
