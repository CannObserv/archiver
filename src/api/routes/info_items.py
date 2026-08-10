"""InfoItem CRUD + sub-resource assignment endpoints."""

import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from co_core.pure.models.changes import InfoItemPrimaryChangedEmit
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.api.deps import get_db_session, get_watcher_client, require_api_key
from src.api.errors import FieldError, raise_422, raise_envelope
from src.api.schemas.info_item import (
    InfoItemCreate,
    InfoItemOut,
    InfoItemRepSpecCreate,
    InfoItemRepSpecOut,
    InfoItemRepSpecPublicUrlPatch,
    InfoItemSourceCreate,
    InfoItemSourceOut,
    InfoItemWatchSpecPut,
)
from src.api.schemas.pagination import Page
from src.api.schemas.types import ULIDStr
from src.api.serializers import (
    info_item_rep_spec_to_out,
    info_item_source_to_out,
    info_item_to_out,
)
from src.core.models import (
    ChangesOutboxRow,
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
    lock_rep_specs,
)
from src.core.tools.bind_info_source import (
    ActiveBindingAlreadyExistsError,
    bind_info_source,
)
from src.core.tools.bind_info_source import (
    InfoItemNotFoundError as BindIIS_InfoItemNotFoundError,
)
from src.core.tools.bind_info_source import (
    InfoSourceNotFoundError as BindIIS_InfoSourceNotFoundError,
)
from src.core.tools.create_info_source import (
    CreateInfoSourceError,
    InvalidSourceSpecError,
    InvalidUrlError,
    MixedAlgorithmFamilyError,
    create_info_source,
)
from src.core.tools.deactivate_info_item_source_binding import (
    BindingNotFoundError,
    deactivate_info_item_source_binding,
)
from src.core.watch_spec_schema.validator import validate_watch_spec
from src.core.watcher_provisioning import (
    provision_on_create,
    sync_on_source_swap,
)

if TYPE_CHECKING:
    from watcher_client import WatcherClient

router = APIRouter(prefix="/info-items", tags=["info-items"])


@router.post("", response_model=InfoItemOut, status_code=201)
async def create_info_item(
    body: InfoItemCreate,
    session: AsyncSession = Depends(get_db_session),
    watcher: "WatcherClient | None" = Depends(get_watcher_client),
) -> InfoItemOut:
    """Create an InfoItem.

    Optionally accepts ``initial_url`` + ``initial_source_specs`` (atomically creates
    a primary InfoSource binding) and ``initial_rep_spec_assignments`` (creates
    effective-dated RepSpec assignments). All writes are a single transaction; any
    validation or lookup failure rolls back the whole thing.
    """
    # --- 1. Look up RepSpecs + validate rep_fields against required_fields ---
    # Locked FOR UPDATE: step 4 below inserts InfoItemRepSpec rows directly
    # rather than going through assign_rep_spec, so without the lock a
    # concurrent update_rep_spec could rewrite a document between this read and
    # our commit — landing an edit on a spec that is being assigned right now
    # (archiver#83 CR). lock_rep_specs sorts IDs to avoid deadlocking against
    # another create naming the same specs in a different order.
    locked_rep_specs = await lock_rep_specs(
        session, [a.rep_spec_id for a in body.initial_rep_spec_assignments]
    )

    rep_spec_rows: list[RepSpec] = []
    for assignment in body.initial_rep_spec_assignments:
        rep_spec = locked_rep_specs.get(str(assignment.rep_spec_id))
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

    # --- 2. Create InfoSource (if requested) BEFORE inserting the InfoItem ---
    info_source: InfoSource | None = None
    if body.initial_url is not None:
        specs = body.initial_source_specs or []
        try:
            info_source = await create_info_source(
                session, url=body.initial_url, source_specs=specs
            )
        except InvalidUrlError as e:
            raise_422("invalid url", kind="domain", source_exc=e)
        except InvalidSourceSpecError as e:
            raise_422("invalid source_spec", kind="schema", errors=e.errors, source_exc=e)
        except MixedAlgorithmFamilyError as e:
            raise_422("mixed algorithm families in source_specs", kind="domain", source_exc=e)
        except CreateInfoSourceError as e:
            raise_422(str(e), kind="domain", source_exc=e)

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

    if info_source is not None:
        await provision_on_create(session, watcher, item, info_source)

    return info_item_to_out(
        item,
        sources=new_sources,
        rep_specs=new_rep_specs,
        base_url=os.environ.get("ARCHIVER_PUBLIC_BASE_URL"),
    )


@router.get("", response_model=Page[InfoItemOut])
async def list_info_items(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0, le=2**63 - 1),
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
                base_url=os.environ.get("ARCHIVER_PUBLIC_BASE_URL"),
            )
            for item in rows
        ],
        has_more=has_more,
        limit=limit,
        offset=offset,
    )


@router.get("/{info_item_id}", response_model=InfoItemOut)
async def get_info_item(
    info_item_id: ULIDStr,
    include_deactivated: bool = Query(
        default=False,
        description=(
            "When true, include deactivated bindings (previous primaries and other "
            "deactivated sources) in info_item_sources. When false (default), only "
            "active bindings are returned."
        ),
    ),
    session: AsyncSession = Depends(get_db_session),
) -> InfoItemOut:
    """Fetch a single InfoItem by ID, including sources and active rep_spec assignments.

    Pass ``include_deactivated=true`` to also include previous primaries and other
    deactivated source bindings in ``info_item_sources``.
    """
    result = await session.execute(select(InfoItem).where(InfoItem.info_item_id == info_item_id))
    item = result.scalar_one_or_none()
    if item is None:
        raise_envelope(404, "lookup", "InfoItem not found")
    sources_q = select(InfoItemSource).where(
        InfoItemSource.info_item_id == item.info_item_id,
    )
    if not include_deactivated:
        sources_q = sources_q.where(InfoItemSource.deactivated_at.is_(None))
    sources = list((await session.execute(sources_q)).scalars().all())
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
    return info_item_to_out(
        item,
        sources=sources,
        rep_specs=rep_specs,
        base_url=os.environ.get("ARCHIVER_PUBLIC_BASE_URL"),
    )


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
    watcher: "WatcherClient | None" = Depends(get_watcher_client),
) -> InfoItemSourceOut:
    """Bind an existing InfoSource to an InfoItem.

    At most one active binding per InfoItem. If one already exists, returns 409 with
    ``data.existing_info_source_id`` — deactivate it first via
    ``DELETE /info-items/{id}/info-sources/{source_id}``, then re-POST.

    Emits ``info_item_primary_changed`` on the change bus
    (``old_info_source_id`` is ``null`` on first assignment).
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
        )
    except BindIIS_InfoItemNotFoundError as e:
        raise_envelope(404, "lookup", "InfoItem not found", source_exc=e)
    except BindIIS_InfoSourceNotFoundError as e:
        raise_envelope(404, "lookup", "InfoSource not found", source_exc=e)
    except ActiveBindingAlreadyExistsError as e:
        raise_envelope(
            409,
            "conflict",
            "an active binding already exists for this InfoItem; "
            "deactivate it first via "
            "DELETE /api/v1/info-items/{info_item_id}/info-sources/{info_source_id}, "
            "then re-POST",
            data={"existing_info_source_id": str(e.existing_info_source_id)},
            source_exc=e,
        )

    # Every binding is a primary binding — emit info_item_primary_changed.
    prev_binding = (
        await session.execute(
            select(InfoItemSource)
            .where(
                InfoItemSource.info_item_id == item_ulid,
                InfoItemSource.deactivated_at.isnot(None),
            )
            .order_by(InfoItemSource.deactivated_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    event = InfoItemPrimaryChangedEmit(
        occurred_at=datetime.now(UTC),
        info_item_id=str(item_ulid),
        old_info_source_id=str(prev_binding.info_source_id) if prev_binding else None,
        new_info_source_id=str(source_ulid),
    )
    session.add(ChangesOutboxRow(topic="info.changes", payload=event.model_dump(mode="json")))

    await session.commit()

    # Best-effort: sync new URL + specs to Watcher
    new_source = await session.get(InfoSource, source_ulid)
    item = await session.get(InfoItem, item_ulid)
    if new_source is not None and item is not None:
        await sync_on_source_swap(session, watcher, item, new_source)

    return info_item_source_to_out(binding)


@router.delete(
    "/{info_item_id}/info-sources/{info_source_id}",
    status_code=200,
    response_model=InfoItemSourceOut,
)
async def deactivate_info_source_binding(
    info_item_id: ULIDStr,
    info_source_id: ULIDStr,
    session: AsyncSession = Depends(get_db_session),
) -> InfoItemSourceOut:
    """Deactivate an InfoItemSource binding (sets ``deactivated_at``).

    Use this to retire the current primary before binding a new one.
    Returns the deactivated binding row. 404 when no active binding exists.
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
        source_ulid = ULID.from_str(info_source_id)
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
        binding = await deactivate_info_item_source_binding(
            session, info_item_id=item_ulid, info_source_id=source_ulid
        )
    except BindingNotFoundError as e:
        raise_envelope(404, "lookup", "Active binding not found", source_exc=e)

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


@router.put(
    "/{info_item_id}/watch-spec",
    response_model=InfoItemOut,
    dependencies=[Depends(require_api_key)],
)
async def put_watch_spec(
    info_item_id: ULIDStr,
    body: InfoItemWatchSpecPut,
    session: AsyncSession = Depends(get_db_session),
) -> InfoItemOut:
    """Replace an InfoItem's scheduling policy.

    A whole-document PUT rather than a general InfoItem PATCH: the document is
    validated as a unit, and omitting ``interval`` is the only way to express
    "the consumer applies its own default" — a merge would make that state
    unreachable once an interval had been set.

    The stored document is left untouched when validation fails.
    """
    result = await session.execute(select(InfoItem).where(InfoItem.info_item_id == info_item_id))
    item = result.scalar_one_or_none()
    if item is None:
        raise_envelope(404, "lookup", "InfoItem not found")

    ok, errors = validate_watch_spec(body.document)
    if not ok:
        raise_422(
            "watch_spec failed schema validation",
            errors=[FieldError(path=e["path"], message=e["message"]) for e in errors],
        )

    item.watch_spec = body.document
    await session.flush()
    await session.commit()
    await session.refresh(item)

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
    return info_item_to_out(
        item,
        sources=sources,
        rep_specs=rep_specs,
        base_url=os.environ.get("ARCHIVER_PUBLIC_BASE_URL"),
    )
