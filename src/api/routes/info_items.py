"""InfoItem CRUD + sub-resource assignment endpoints."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.api.deps import get_db_session, require_api_key
from src.api.schemas.info_item import (
    InfoItemCreate,
    InfoItemOut,
    InfoItemRepSpecCreate,
    InfoItemRepSpecOut,
    InfoItemRepSpecPublicUrlPatch,
    InfoItemSourceCreate,
    InfoItemSourceOut,
    InfoItemSourceRevisionCreate,
    InfoItemSourceRevisionOut,
)
from src.api.schemas.types import ULIDStr
from src.api.serializers import (
    info_item_rep_spec_to_out,
    info_item_source_revision_to_out,
    info_item_source_to_out,
    info_item_to_out,
)
from src.core.models import (
    InfoItem,
    InfoItemRepSpec,
    InfoItemSource,
    InfoSource,
    RepSpec,
)
from src.core.rep_fields_schema.validator import validate_rep_fields_against_spec
from src.core.tools.assign_rep_spec import (
    InfoItemNotFoundError as AssignInfoItemNotFoundError,
)
from src.core.tools.assign_rep_spec import (
    RepFieldsIncompleteError,
    RepSpecNotFoundError,
    assign_rep_spec,
)
from src.core.tools.bind_revision import (
    InfoItemNotFoundError as BindInfoItemNotFoundError,
)
from src.core.tools.bind_revision import (
    SourceRevisionNotFoundError,
    bind_revision,
)
from src.core.tools.create_info_source import (
    DuplicateUrlError,
    InvalidSourceSpecError,
    create_info_source,
)

router = APIRouter(prefix="/info-items", tags=["info-items"])


@router.post("", response_model=InfoItemOut, status_code=201)
async def create_info_item(
    body: InfoItemCreate, session: AsyncSession = Depends(get_db_session)
) -> InfoItemOut:
    """Create an InfoItem.

    Optionally accepts ``initial_source_spec`` (creates a primary InfoSource
    binding) and ``initial_rep_spec_assignments`` (creates effective-dated
    RepSpec assignments). All writes are a single transaction; any validation
    or lookup failure rolls back the whole thing.
    """
    # --- 1. Look up RepSpecs + validate rep_fields against required_fields ---
    rep_spec_rows: list[RepSpec] = []
    for assignment in body.initial_rep_spec_assignments:
        result = await session.execute(
            select(RepSpec).where(RepSpec.rep_spec_id == assignment.rep_spec_id)
        )
        rep_spec = result.scalar_one_or_none()
        if rep_spec is None:
            raise HTTPException(
                status_code=404,
                detail=f"RepSpec {assignment.rep_spec_id!r} not found",
            )
        rep_spec_rows.append(rep_spec)

        required_fields: list[str] = rep_spec.document.get("required_fields", [])
        if required_fields:
            ok, errors = validate_rep_fields_against_spec(body.rep_fields, required_fields)
            if not ok:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "message": (
                            f"rep_fields does not satisfy RepSpec {assignment.rep_spec_id!r}"
                        ),
                        "errors": errors,
                    },
                )

    # --- 2. Create InfoSource (if requested) BEFORE inserting the InfoItem.
    # Surfacing duplicate-URL collisions as 409 here keeps the all-or-nothing
    # contract: no InfoItem row is flushed when the InfoSource insert fails.
    info_source: InfoSource | None = None
    if body.initial_source_spec is not None:
        try:
            info_source = await create_info_source(session, source_spec=body.initial_source_spec)
        except InvalidSourceSpecError as e:
            raise HTTPException(
                status_code=422,
                detail={"message": "invalid source_spec", "errors": e.errors},
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

    # --- 3. Insert InfoItem + binding ---
    item = InfoItem(
        name=body.name,
        description=body.description,
        owner=body.owner,
        rep_fields=body.rep_fields,
    )
    session.add(item)
    await session.flush()  # populate item.info_item_id

    new_sources: list[InfoItemSource] = []
    if info_source is not None:
        binding = InfoItemSource(
            info_item_id=item.info_item_id,
            info_source_id=info_source.info_source_id,
            role="primary",
        )
        session.add(binding)
        await session.flush()
        new_sources.append(binding)

    # --- 4. Insert InfoItemRepSpec rows ---
    new_rep_specs: list[InfoItemRepSpec] = []
    for assignment, rep_spec in zip(body.initial_rep_spec_assignments, rep_spec_rows):
        activated_at = assignment.activated_at or datetime.now(UTC)
        airs = InfoItemRepSpec(
            info_item_id=item.info_item_id,
            rep_spec_id=rep_spec.rep_spec_id,
            activated_at=activated_at,
        )
        session.add(airs)
        new_rep_specs.append(airs)

    await session.flush()
    await session.commit()
    await session.refresh(item)

    return info_item_to_out(item, sources=new_sources, rep_specs=new_rep_specs)


@router.get("", response_model=list[InfoItemOut])
async def list_info_items(
    session: AsyncSession = Depends(get_db_session),
) -> list[InfoItemOut]:
    """List all InfoItems (no related rows populated)."""
    result = await session.execute(select(InfoItem).order_by(InfoItem.created_at))
    return [info_item_to_out(item) for item in result.scalars().all()]


@router.get("/{info_item_id}", response_model=InfoItemOut)
async def get_info_item(
    info_item_id: ULIDStr, session: AsyncSession = Depends(get_db_session)
) -> InfoItemOut:
    """Fetch a single InfoItem by ID (no related rows populated)."""
    result = await session.execute(select(InfoItem).where(InfoItem.info_item_id == info_item_id))
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="InfoItem not found")
    return info_item_to_out(item)


# ---------------------------------------------------------------------------
# Sub-resource assignment endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/{info_item_id}/info-sources",
    response_model=InfoItemSourceOut,
    status_code=201,
)
async def add_info_source(
    info_item_id: ULIDStr,
    body: InfoItemSourceCreate,
    session: AsyncSession = Depends(get_db_session),
) -> InfoItemSourceOut:
    """Declare a binding between an InfoItem and an existing InfoSource.

    Looks up both entities; returns 404 if either doesn't exist. The binding
    is a new ``info_item_sources`` row with the requested role.
    """
    item = await session.get(InfoItem, ULID.from_str(info_item_id))
    if item is None:
        raise HTTPException(status_code=404, detail="InfoItem not found")

    try:
        source_ulid = ULID.from_str(body.info_source_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="info_source_id is not a valid ULID")

    source = await session.get(InfoSource, source_ulid)
    if source is None:
        raise HTTPException(status_code=404, detail="InfoSource not found")

    binding = InfoItemSource(
        info_item_id=item.info_item_id,
        info_source_id=source.info_source_id,
        role=body.role,
    )
    session.add(binding)
    await session.flush()
    await session.commit()

    return info_item_source_to_out(binding)


@router.post(
    "/{info_item_id}/rep-spec-assignments",
    response_model=InfoItemRepSpecOut,
    status_code=201,
)
async def add_rep_spec_assignment(
    info_item_id: ULIDStr,
    body: InfoItemRepSpecCreate,
    session: AsyncSession = Depends(get_db_session),
) -> InfoItemRepSpecOut:
    """Assign a RepSpec to an InfoItem with effective dating.

    Validates that the InfoItem exists, the RepSpec exists, and the InfoItem's
    rep_fields satisfies the RepSpec's required_fields. Returns 201 on success.

    Error responses:
    - 404: InfoItem or RepSpec not found
    - 422: rep_fields incomplete (missing required fields)
    """
    try:
        item_ulid = ULID.from_str(info_item_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="info_item_id is not a valid ULID")

    try:
        spec_ulid = ULID.from_str(body.rep_spec_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="rep_spec_id is not a valid ULID")

    try:
        assignment = await assign_rep_spec(
            session,
            info_item_id=item_ulid,
            rep_spec_id=spec_ulid,
            activated_at=body.activated_at,
        )
    except AssignInfoItemNotFoundError:
        raise HTTPException(status_code=404, detail="InfoItem not found")
    except RepSpecNotFoundError:
        raise HTTPException(status_code=404, detail="RepSpec not found")
    except RepFieldsIncompleteError as e:
        raise HTTPException(
            status_code=422,
            detail={"detail": {"missing": e.missing}},
        )

    await session.commit()
    return info_item_rep_spec_to_out(assignment)


@router.post(
    "/{info_item_id}/source-revisions",
    response_model=InfoItemSourceRevisionOut,
    status_code=201,
)
async def bind_source_revision(
    info_item_id: ULIDStr,
    body: InfoItemSourceRevisionCreate,
    session: AsyncSession = Depends(get_db_session),
) -> InfoItemSourceRevisionOut:
    """Bind a SourceRevision to an InfoItem (idempotent).

    If a binding for (info_item_id, source_revision_id) already exists, it is
    returned unchanged. Returns 404 if the InfoItem or SourceRevision doesn't exist.
    """
    try:
        item_ulid = ULID.from_str(info_item_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="info_item_id is not a valid ULID")

    try:
        rev_ulid = ULID.from_str(body.source_revision_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="source_revision_id is not a valid ULID")

    try:
        binding = await bind_revision(
            session,
            info_item_id=item_ulid,
            source_revision_id=rev_ulid,
            bound_at=body.bound_at,
        )
    except BindInfoItemNotFoundError:
        raise HTTPException(status_code=404, detail="InfoItem not found")
    except SourceRevisionNotFoundError:
        raise HTTPException(status_code=404, detail="SourceRevision not found")

    await session.commit()
    return info_item_source_revision_to_out(binding)


@router.delete(
    "/{info_item_id}/rep-spec-assignments/{assignment_id}",
    status_code=204,
)
async def deactivate_rep_spec_assignment(
    info_item_id: ULIDStr,
    assignment_id: ULIDStr,
    session: AsyncSession = Depends(get_db_session),
) -> None:
    """Deactivate a RepSpec assignment by setting ``deactivated_at = now()``.

    Returns 204 on success. Returns 404 if the assignment doesn't exist or
    does not belong to the given InfoItem.
    """
    try:
        assign_ulid = ULID.from_str(assignment_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="assignment_id is not a valid ULID")

    assignment = await session.get(InfoItemRepSpec, assign_ulid)
    if assignment is None or str(assignment.info_item_id) != info_item_id:
        raise HTTPException(status_code=404, detail="Assignment not found")

    assignment.deactivated_at = datetime.now(UTC)
    await session.flush()
    await session.commit()


@router.patch(
    "/{info_item_id}/rep-spec-assignments/{assignment_id}",
    response_model=InfoItemRepSpecOut,
    dependencies=[Depends(require_api_key)],
)
async def patch_rep_spec_assignment_public_url(
    info_item_id: ULIDStr,
    assignment_id: ULIDStr,
    body: InfoItemRepSpecPublicUrlPatch,
    session: AsyncSession = Depends(get_db_session),
) -> InfoItemRepSpecOut:
    """Write a provider-native public URL back to a RepSpec assignment.

    Called by Replicator after a successful replication job. Works on both
    active and deactivated rows (history preservation). Returns 404 if the
    assignment doesn't exist or doesn't belong to the given InfoItem.
    """
    try:
        assign_ulid = ULID.from_str(assignment_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="assignment_id is not a valid ULID")

    assignment = await session.get(InfoItemRepSpec, assign_ulid)
    if assignment is None or str(assignment.info_item_id) != info_item_id:
        raise HTTPException(
            status_code=404,
            detail="rep_spec_assignment not found for this info_item",
        )

    assignment.public_url = body.public_url
    await session.flush()
    await session.commit()
    await session.refresh(assignment)
    return info_item_rep_spec_to_out(assignment)
