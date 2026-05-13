"""POST /source-revisions and PATCH /source-revisions/{id} route handlers."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
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
from src.core.changes.payloads import SourceRevisionCapturedEvent
from src.core.models import ChangesOutboxRow, InfoItemSource, InfoSource, SourceRevision

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

    source = await session.get(InfoSource, source_ulid)
    if source is None:
        raise_envelope(404, "lookup", "info_source not found")

    # --- Reject ULID collisions against a different (source, fingerprint) ---
    # Idempotent-match cases (same ULID, same pair) fall through to the
    # ON CONFLICT path below.
    if rev_ulid is not None:
        existing = await session.get(SourceRevision, rev_ulid)
        if existing is not None and (
            existing.info_source_id != source_ulid
            or existing.content_fingerprint != body.content_fingerprint
        ):
            raise_envelope(
                409,
                "conflict",
                "source_revision_id already in use for a different "
                "(info_source_id, content_fingerprint) pair",
                data={
                    "existing_info_source_id": str(existing.info_source_id),
                    "existing_content_fingerprint": existing.content_fingerprint,
                },
            )

    # --- Upsert via INSERT … ON CONFLICT DO NOTHING … RETURNING ---
    insert_values: dict = {
        "info_source_id": source_ulid,
        "content_fingerprint": body.content_fingerprint,
        "captured_at": body.captured_at,
        "content_size_bytes": body.content_size_bytes,
        "content_media_type": body.content_media_type,
        "content_cache_uri": body.content_cache_uri,
        "content_cache_expires_at": body.content_cache_expires_at,
    }
    if rev_ulid is not None:
        insert_values["source_revision_id"] = rev_ulid

    stmt = (
        pg_insert(SourceRevision)
        .values(**insert_values)
        .on_conflict_do_nothing(index_elements=["info_source_id", "content_fingerprint"])
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
        inserted = False
    else:
        response.status_code = status.HTTP_201_CREATED
        inserted = True

    if inserted:
        # Query active info_item_ids bound to this source
        item_ids_result = await session.execute(
            select(InfoItemSource.info_item_id).where(
                InfoItemSource.info_source_id == row.info_source_id,
                InfoItemSource.deactivated_at.is_(None),
            )
        )
        info_item_ids = [str(iid) for iid in item_ids_result.scalars()]
        event = SourceRevisionCapturedEvent(
            occurred_at=datetime.now(UTC),
            info_source_id=str(row.info_source_id),
            source_revision_id=str(row.source_revision_id),
            content_fingerprint=row.content_fingerprint,
            info_item_ids=info_item_ids,
        )
        session.add(ChangesOutboxRow(topic="info.changes", payload=event.model_dump(mode="json")))

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
