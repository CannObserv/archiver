"""InfoItem CRUD + sub-resource assignment endpoints."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.api.deps import get_db_session, require_api_key
from src.api.errors import FieldError, raise_422, raise_envelope
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
from src.api.schemas.pagination import Page
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
from src.core.tools.bind_info_source import (
    ActiveRootMissingError,
    AlgorithmFamilyMismatchError,
    FragmentParentMismatchError,
    RoleShapeMismatchError,
    bind_info_source,
)
from src.core.tools.bind_info_source import (
    InfoItemNotFoundError as BindIIS_InfoItemNotFoundError,
)
from src.core.tools.bind_info_source import (
    InfoSourceNotFoundError as BindIIS_InfoSourceNotFoundError,
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
            raise_envelope(
                404,
                "lookup",
                f"RepSpec {assignment.rep_spec_id!r} not found",
            )
        rep_spec_rows.append(rep_spec)

        required_fields: list[str] = rep_spec.document.get("required_fields", [])
        if required_fields:
            ok, errors = validate_rep_fields_against_spec(body.rep_fields, required_fields)
            if not ok:
                raise_422(
                    f"rep_fields does not satisfy RepSpec {assignment.rep_spec_id!r}",
                    kind="domain",
                    errors=[
                        FieldError(
                            path=e.get("path", ""),
                            message=e.get("message", "missing"),
                            code="rep_fields_incomplete",
                        )
                        for e in errors
                    ],
                    data={"rep_spec_id": str(assignment.rep_spec_id)},
                )

    # --- 2. Create InfoSource (if requested) BEFORE inserting the InfoItem.
    # Surfacing duplicate-URL collisions as 409 here keeps the all-or-nothing
    # contract: no InfoItem row is flushed when the InfoSource insert fails.
    info_source: InfoSource | None = None
    if body.initial_source_spec is not None:
        try:
            info_source = await create_info_source(session, source_spec=body.initial_source_spec)
        except InvalidSourceSpecError as e:
            raise_422("invalid source_spec", kind="schema", errors=e.errors, source_exc=e)
        except DuplicateUrlError as e:
            raise_envelope(
                409,
                "conflict",
                "an InfoSource already exists for this URL",
                data={"url": e.url, "existing_info_source_id": str(e.existing_info_source_id)},
                source_exc=e,
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

    # Atomic-create only supports a single initial_source_spec (becomes the
    # NULL-role / root binding). If initial fragment specs are added later,
    # they must run through bind_info_source for the family-compatibility
    # check (archiver#22).
    new_sources: list[InfoItemSource] = []
    if info_source is not None:
        binding = InfoItemSource(
            info_item_id=item.info_item_id,
            info_source_id=info_source.info_source_id,
            role=None,
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


@router.get("", response_model=Page[InfoItemOut])
async def list_info_items(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db_session),
) -> Page[InfoItemOut]:
    """List InfoItems with offset pagination, including active sources and rep_spec assignments.

    ``has_more`` is derived via a ``limit+1`` probe; no total count is computed.
    Active ``info_item_sources`` and ``info_item_rep_specs`` are batch-loaded in
    two additional queries (not N+1).
    """
    stmt = (
        select(InfoItem)
        .order_by(InfoItem.created_at, InfoItem.info_item_id)
        .offset(offset)
        .limit(limit + 1)
    )
    rows = list((await session.execute(stmt)).scalars().all())
    has_more = len(rows) > limit
    rows = rows[:limit]

    if not rows:
        return Page[InfoItemOut](items=[], has_more=False, limit=limit, offset=offset)

    item_ids = [r.info_item_id for r in rows]

    sources_rows = (
        (
            await session.execute(
                select(InfoItemSource).where(
                    InfoItemSource.info_item_id.in_(item_ids),
                    InfoItemSource.deactivated_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    sources_by_item: dict = {}
    for s in sources_rows:
        sources_by_item.setdefault(s.info_item_id, []).append(s)

    rep_specs_rows = (
        (
            await session.execute(
                select(InfoItemRepSpec).where(
                    InfoItemRepSpec.info_item_id.in_(item_ids),
                    InfoItemRepSpec.deactivated_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    rep_specs_by_item: dict = {}
    for r in rep_specs_rows:
        rep_specs_by_item.setdefault(r.info_item_id, []).append(r)

    return Page[InfoItemOut](
        items=[
            info_item_to_out(
                item,
                sources=sources_by_item.get(item.info_item_id, []),
                rep_specs=rep_specs_by_item.get(item.info_item_id, []),
            )
            for item in rows
        ],
        has_more=has_more,
        limit=limit,
        offset=offset,
    )


@router.get("/{info_item_id}", response_model=InfoItemOut)
async def get_info_item(
    info_item_id: ULIDStr, session: AsyncSession = Depends(get_db_session)
) -> InfoItemOut:
    """Fetch a single InfoItem by ID, including active sources and rep_spec assignments."""
    result = await session.execute(select(InfoItem).where(InfoItem.info_item_id == info_item_id))
    item = result.scalar_one_or_none()
    if item is None:
        raise_envelope(404, "lookup", "InfoItem not found")
    sources = list(
        (
            await session.execute(
                select(InfoItemSource).where(
                    InfoItemSource.info_item_id == item.info_item_id,
                    InfoItemSource.deactivated_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    rep_specs = list(
        (
            await session.execute(
                select(InfoItemRepSpec).where(
                    InfoItemRepSpec.info_item_id == item.info_item_id,
                    InfoItemRepSpec.deactivated_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    return info_item_to_out(item, sources=sources, rep_specs=rep_specs)


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
    """Bind an existing InfoSource to an InfoItem.

    ``body.role`` is ``null`` for a root-shaped InfoSource (the InfoItem's
    primary; at most one active per InfoItem) or one of
    ``'cross_check'`` / ``'sub_aspect'`` for a fragment-shaped InfoSource
    whose parent equals the InfoItem's active root binding's source.
    """
    try:
        item_ulid = ULID.from_str(info_item_id)
    except ValueError as e:
        raise_envelope(
            422,
            "domain",
            "info_item_id is not a valid ULID",
            errors=[
                FieldError(path="/info_item_id", message="not a valid ULID", code="invalid_ulid")
            ],
            source_exc=e,
        )

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

    try:
        binding = await bind_info_source(
            session,
            info_item_id=item_ulid,
            info_source_id=source_ulid,
            role=body.role,
        )
    except BindIIS_InfoItemNotFoundError as e:
        raise_envelope(404, "lookup", "InfoItem not found", source_exc=e)
    except BindIIS_InfoSourceNotFoundError as e:
        raise_envelope(404, "lookup", "InfoSource not found", source_exc=e)
    except RoleShapeMismatchError as e:
        raise_envelope(
            422,
            "domain",
            f"role {e.role!r} is not valid for "
            f"{'root' if e.source_is_root else 'fragment'}-shaped InfoSource",
            errors=[
                FieldError(path="/role", message="role/shape mismatch", code="role_shape_mismatch")
            ],
            source_exc=e,
        )
    except ActiveRootMissingError as e:
        raise_envelope(
            422,
            "domain",
            "cannot bind a fragment-role InfoSource before an active root binding exists",
            errors=[
                FieldError(
                    path="/info_source_id",
                    message="InfoItem has no active root binding",
                    code="active_root_missing",
                )
            ],
            source_exc=e,
        )
    except FragmentParentMismatchError as e:
        raise_envelope(
            422,
            "domain",
            "fragment's parent does not match the InfoItem's active root binding",
            errors=[
                FieldError(
                    path="/info_source_id",
                    message="fragment parent != active root source",
                    code="fragment_parent_mismatch",
                )
            ],
            data={
                "expected_root_info_source_id": str(e.expected_root_id),
                "actual_parent_info_source_id": str(e.actual_parent_id),
            },
            source_exc=e,
        )
    except AlgorithmFamilyMismatchError as e:
        raise_envelope(
            422,
            "domain",
            "fragment algorithm does not match the InfoItem's primary algorithm family",
            errors=[
                FieldError(
                    path="/extraction/algorithm",
                    message=(
                        f"algorithm {e.actual_algorithm!r} is in a different "
                        f"content-kind family than the primary ({e.expected_family!r})"
                    ),
                    code="algorithm_family_mismatch",
                )
            ],
            data={
                "expected_family": e.expected_family,
                "actual_algorithm": e.actual_algorithm,
            },
            source_exc=e,
        )

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
    except ValueError as e:
        raise_envelope(
            422,
            "domain",
            "info_item_id is not a valid ULID",
            errors=[
                FieldError(
                    path="/info_item_id",
                    message="not a valid ULID",
                    code="invalid_ulid",
                )
            ],
            source_exc=e,
        )

    try:
        spec_ulid = ULID.from_str(body.rep_spec_id)
    except ValueError as e:
        raise_envelope(
            422,
            "domain",
            "rep_spec_id is not a valid ULID",
            errors=[
                FieldError(
                    path="/rep_spec_id",
                    message="not a valid ULID",
                    code="invalid_ulid",
                )
            ],
            source_exc=e,
        )

    try:
        assignment = await assign_rep_spec(
            session,
            info_item_id=item_ulid,
            rep_spec_id=spec_ulid,
            activated_at=body.activated_at,
        )
    except AssignInfoItemNotFoundError as e:
        raise_envelope(404, "lookup", "InfoItem not found", source_exc=e)
    except RepSpecNotFoundError as e:
        raise_envelope(404, "lookup", "RepSpec not found", source_exc=e)
    except RepFieldsIncompleteError as e:
        raise_422(
            "rep_fields incomplete",
            kind="domain",
            errors=[
                FieldError(
                    path=m.get("path", ""),
                    message=m.get("message", "missing"),
                    code="rep_fields_incomplete",
                )
                for m in e.missing
            ],
            source_exc=e,
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
    except ValueError as e:
        raise_envelope(
            422,
            "domain",
            "info_item_id is not a valid ULID",
            errors=[
                FieldError(
                    path="/info_item_id",
                    message="not a valid ULID",
                    code="invalid_ulid",
                )
            ],
            source_exc=e,
        )

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

    try:
        binding = await bind_revision(
            session,
            info_item_id=item_ulid,
            source_revision_id=rev_ulid,
            bound_at=body.bound_at,
        )
    except BindInfoItemNotFoundError as e:
        raise_envelope(404, "lookup", "InfoItem not found", source_exc=e)
    except SourceRevisionNotFoundError as e:
        raise_envelope(404, "lookup", "SourceRevision not found", source_exc=e)

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
    except ValueError as e:
        raise_envelope(
            422,
            "domain",
            "assignment_id is not a valid ULID",
            errors=[
                FieldError(
                    path="/assignment_id",
                    message="not a valid ULID",
                    code="invalid_ulid",
                )
            ],
            source_exc=e,
        )

    assignment = await session.get(InfoItemRepSpec, assign_ulid)
    if assignment is None or str(assignment.info_item_id) != info_item_id:
        raise_envelope(404, "lookup", "Assignment not found")

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
    except ValueError as e:
        raise_envelope(
            422,
            "domain",
            "assignment_id is not a valid ULID",
            errors=[
                FieldError(
                    path="/assignment_id",
                    message="not a valid ULID",
                    code="invalid_ulid",
                )
            ],
            source_exc=e,
        )

    assignment = await session.get(InfoItemRepSpec, assign_ulid)
    if assignment is None or str(assignment.info_item_id) != info_item_id:
        raise_envelope(404, "lookup", "rep_spec_assignment not found for this info_item")

    assignment.public_url = body.public_url
    await session.flush()
    await session.commit()
    await session.refresh(assignment)
    return info_item_rep_spec_to_out(assignment)
