"""Dashboard — Information Items (list, detail, create, sub-resource mutations)."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.api.deps import get_db_session
from src.api.errors import raise_envelope
from src.core.models import (
    InfoItem,
    InfoItemRepSpec,
    InfoItemSource,
    InfoItemSourceRevision,
    InfoSource,
    RepSpec,
    SourceRevision,
)
from src.core.tools.assign_rep_spec import (
    InfoItemNotFoundError as AssignItemNotFoundError,
)
from src.core.tools.assign_rep_spec import (
    RepFieldsIncompleteError,
    RepSpecNotFoundError,
    assign_rep_spec,
)
from src.core.tools.bind_info_source import (
    ActiveBindingAlreadyExistsError,
    bind_info_source,
)
from src.core.tools.bind_info_source import (
    InfoItemNotFoundError as BindItemNotFoundError,
)
from src.core.tools.bind_info_source import (
    InfoSourceNotFoundError as BindSourceNotFoundError,
)
from src.core.tools.bind_revision import (
    InfoItemNotFoundError as BindRevItemNotFoundError,
)
from src.core.tools.bind_revision import (
    SourceRevisionNotFoundError,
    bind_revision,
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
from src.dashboard.deps import get_dashboard_user

router = APIRouter(prefix="/dashboard/info-items", tags=["dashboard-info-items"])

_templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@dataclass
class _ItemRow:
    item: InfoItem
    primary_url: str | None
    primary_info_source_id: ULID | None
    observed_at: datetime | None


async def _resolve_item(item_id: str, session: AsyncSession) -> InfoItem:
    """Fetch InfoItem by ULID string or raise 404."""
    try:
        uid = ULID.from_str(item_id)
    except Exception as e:
        raise_envelope(404, "lookup", "Information Item not found", source_exc=e)
    item = await session.get(InfoItem, uid)
    if item is None:
        raise_envelope(404, "lookup", "Information Item not found")
    return item


# ---------------------------------------------------------------------------
# GET /dashboard/info-items/
# ---------------------------------------------------------------------------


@router.get("/", response_class=HTMLResponse)
async def list_info_items(
    request: Request,
    name_contains: str | None = None,
    limit: int = 50,
    offset: int = 0,
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """Paginated list with optional name search."""
    stmt = select(InfoItem).order_by(InfoItem.created_at, InfoItem.info_item_id)
    if name_contains:
        stmt = stmt.where(InfoItem.name.ilike(f"%{name_contains}%"))
    stmt = stmt.offset(offset).limit(limit + 1)

    rows = list((await session.execute(stmt)).scalars().all())
    has_more = len(rows) > limit
    rows = rows[:limit]

    item_ids = [r.info_item_id for r in rows]

    # Batch-load active root bindings to get primary URL
    primary_bindings: dict[ULID, InfoItemSource] = {}
    if item_ids:
        iis_rows = (
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
        for iis in iis_rows:
            primary_bindings[iis.info_item_id] = iis

    # Batch-load InfoSource URLs for the primary bindings
    source_urls: dict[ULID, str | None] = {}
    primary_source_ids = [b.info_source_id for b in primary_bindings.values()]
    if primary_source_ids:
        src_rows = (
            (
                await session.execute(
                    select(InfoSource).where(InfoSource.info_source_id.in_(primary_source_ids))
                )
            )
            .scalars()
            .all()
        )
        for src in src_rows:
            source_urls[src.info_source_id] = src.url

    # Batch-load most-recent captured_at per primary source
    observed_by_source: dict[ULID, datetime] = {}
    if primary_source_ids:
        obs_rows = (
            await session.execute(
                select(
                    SourceRevision.info_source_id,
                    func.max(SourceRevision.captured_at).label("latest"),
                )
                .where(SourceRevision.info_source_id.in_(primary_source_ids))
                .group_by(SourceRevision.info_source_id)
            )
        ).all()
        for obs in obs_rows:
            observed_by_source[obs.info_source_id] = obs.latest

    items: list[_ItemRow] = []
    for item in rows:
        binding = primary_bindings.get(item.info_item_id)
        primary_url = source_urls.get(binding.info_source_id) if binding else None
        items.append(
            _ItemRow(
                item=item,
                primary_url=primary_url,
                primary_info_source_id=binding.info_source_id if binding else None,
                observed_at=observed_by_source.get(binding.info_source_id) if binding else None,
            )
        )

    return _templates.TemplateResponse(
        request,
        "info_items/list.html",
        {
            "user": user,
            "items": items,
            "has_more": has_more,
            "limit": limit,
            "offset": offset,
            "name_contains": name_contains or "",
        },
    )


# ---------------------------------------------------------------------------
# GET /dashboard/info-items/new  (must precede /{item_id})
# ---------------------------------------------------------------------------


@router.get("/new", response_class=HTMLResponse)
async def new_info_item_form(
    request: Request,
    user=Depends(get_dashboard_user),
) -> HTMLResponse:
    """Render the multi-step create wizard."""
    return _templates.TemplateResponse(
        request,
        "info_items/new.html",
        {"user": user, "errors": {}},
    )


# ---------------------------------------------------------------------------
# POST /dashboard/info-items/new
# ---------------------------------------------------------------------------


@router.post("/new")
async def create_info_item(
    request: Request,
    name: str = Form(...),
    description: str | None = Form(default=None),
    owner: str | None = Form(default=None),
    rep_fields: str = Form(default="{}"),
    initial_url: str | None = Form(default=None),
    initial_source_specs: str | None = Form(default=None),
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    """Create an InfoItem, optionally with an initial InfoSource binding."""
    name = name.strip()
    description = description.strip() if description else None
    owner = owner.strip() if owner else None
    errors: dict[str, str] = {}

    if not name:
        errors["name"] = "Name is required."

    rep_fields_dict: dict = {}
    try:
        rep_fields_dict = json.loads(rep_fields or "{}")
        if not isinstance(rep_fields_dict, dict):
            errors["rep_fields"] = "Must be a JSON object."
    except json.JSONDecodeError:
        errors["rep_fields"] = "Invalid JSON."

    source_specs_list: list | None = None
    if initial_source_specs and initial_source_specs.strip():
        try:
            source_specs_list = json.loads(initial_source_specs)
            if not isinstance(source_specs_list, list):
                errors["initial_source_specs"] = "Must be a JSON array."
        except json.JSONDecodeError:
            errors["initial_source_specs"] = "Invalid JSON."

    if errors:
        return _templates.TemplateResponse(
            request,
            "info_items/new.html",
            {"user": user, "errors": errors},
            status_code=422,
        )

    info_source = None
    url_val = initial_url.strip() if initial_url else None
    if url_val:
        try:
            info_source = await create_info_source(
                session, url=url_val, source_specs=source_specs_list or []
            )
        except (InvalidUrlError, InvalidSourceSpecError, MixedAlgorithmFamilyError) as e:
            msg = (
                getattr(e, "errors", [{}])[0].get("message", str(e))
                if hasattr(e, "errors")
                else str(e)
            )
            errors["initial_url"] = f"Could not create InfoSource: {msg}"
            return _templates.TemplateResponse(
                request,
                "info_items/new.html",
                {"user": user, "errors": errors},
                status_code=422,
            )
        except CreateInfoSourceError as e:
            errors["initial_url"] = str(e)
            return _templates.TemplateResponse(
                request,
                "info_items/new.html",
                {"user": user, "errors": errors},
                status_code=422,
            )

    item = InfoItem(
        name=name,
        description=description or None,
        owner=owner or None,
        rep_fields=rep_fields_dict,
    )
    session.add(item)
    await session.flush()

    if info_source is not None:
        binding = InfoItemSource(
            info_item_id=item.info_item_id,
            info_source_id=info_source.info_source_id,
        )
        session.add(binding)
        await session.flush()

    await session.commit()

    return RedirectResponse(
        url=f"/dashboard/info-items/{item.info_item_id}",
        status_code=303,
    )


# ---------------------------------------------------------------------------
# GET /dashboard/info-items/{item_id}
# ---------------------------------------------------------------------------


@router.get("/{item_id}", response_class=HTMLResponse)
async def detail_info_item(
    request: Request,
    item_id: str,
    tab: str = "sources",
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """Detail page with Sources / Replication Specs / Revision History tabs."""
    item = await _resolve_item(item_id, session)

    # Active source bindings + InfoSource rows for display
    iis_rows = list(
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
    source_ids = [b.info_source_id for b in iis_rows]
    sources_by_id: dict[ULID, InfoSource] = {}
    if source_ids:
        for src in (
            await session.execute(
                select(InfoSource).where(InfoSource.info_source_id.in_(source_ids))
            )
        ).scalars():
            sources_by_id[src.info_source_id] = src

    # Active rep_spec assignments + RepSpec rows
    irs_rows = list(
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
    rs_ids = [a.rep_spec_id for a in irs_rows]
    rep_specs_by_id: dict[ULID, RepSpec] = {}
    if rs_ids:
        for rs in (
            await session.execute(select(RepSpec).where(RepSpec.rep_spec_id.in_(rs_ids)))
        ).scalars():
            rep_specs_by_id[rs.rep_spec_id] = rs

    # Revision history (last 50)
    iisr_rows = list(
        (
            await session.execute(
                select(InfoItemSourceRevision)
                .where(InfoItemSourceRevision.info_item_id == item.info_item_id)
                .order_by(InfoItemSourceRevision.bound_at.desc())
                .limit(50)
            )
        )
        .scalars()
        .all()
    )
    rev_ids = [r.source_revision_id for r in iisr_rows]
    revisions_by_id: dict[ULID, SourceRevision] = {}
    if rev_ids:
        for rev in (
            await session.execute(
                select(SourceRevision).where(SourceRevision.source_revision_id.in_(rev_ids))
            )
        ).scalars():
            revisions_by_id[rev.source_revision_id] = rev

    return _templates.TemplateResponse(
        request,
        "info_items/detail.html",
        {
            "user": user,
            "item": item,
            "iis_rows": iis_rows,
            "sources_by_id": sources_by_id,
            "irs_rows": irs_rows,
            "rep_specs_by_id": rep_specs_by_id,
            "iisr_rows": iisr_rows,
            "revisions_by_id": revisions_by_id,
            "active_tab": tab,
        },
    )


# ---------------------------------------------------------------------------
# POST /{item_id}/bind-source
# ---------------------------------------------------------------------------


@router.post("/{item_id}/bind-source")
async def bind_source(
    item_id: str,
    info_source_id: str = Form(...),
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    """Bind an existing InfoSource to this InfoItem."""
    try:
        item_ulid = ULID.from_str(item_id)
    except Exception as e:
        raise_envelope(404, "lookup", "Information Item not found", source_exc=e)

    try:
        source_ulid = ULID.from_str(info_source_id)
    except Exception as e:
        raise_envelope(422, "domain", "info_source_id is not a valid ULID", source_exc=e)

    try:
        await bind_info_source(session, info_item_id=item_ulid, info_source_id=source_ulid)
    except BindItemNotFoundError as e:
        raise_envelope(404, "lookup", "Information Item not found", source_exc=e)
    except BindSourceNotFoundError as e:
        raise_envelope(404, "lookup", "Information Source not found", source_exc=e)
    except ActiveBindingAlreadyExistsError as e:
        raise_envelope(
            409, "conflict", "An active binding already exists for this item", source_exc=e
        )

    await session.commit()
    return RedirectResponse(
        url=f"/dashboard/info-items/{item_id}?tab=sources",
        status_code=303,
    )


# ---------------------------------------------------------------------------
# DELETE /{item_id}/info-sources/{source_id}
# ---------------------------------------------------------------------------


@router.delete("/{item_id}/info-sources/{source_id}")
async def deactivate_source_binding(
    item_id: str,
    source_id: str,
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    """Set deactivated_at on an InfoItemSource binding (HTMX — removes row)."""
    try:
        item_ulid = ULID.from_str(item_id)
        source_ulid = ULID.from_str(source_id)
    except Exception as e:
        raise_envelope(404, "lookup", "Binding not found", source_exc=e)

    try:
        await deactivate_info_item_source_binding(
            session, info_item_id=item_ulid, info_source_id=source_ulid
        )
    except BindingNotFoundError as e:
        raise_envelope(404, "lookup", "Active binding not found", source_exc=e)

    await session.commit()
    return Response(status_code=200)


# ---------------------------------------------------------------------------
# POST /{item_id}/assign-rep-spec
# ---------------------------------------------------------------------------


@router.post("/{item_id}/assign-rep-spec")
async def assign_rep_spec_route(
    item_id: str,
    rep_spec_id: str = Form(...),
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    """Assign a RepSpec to this InfoItem."""
    try:
        item_ulid = ULID.from_str(item_id)
    except Exception as e:
        raise_envelope(404, "lookup", "Information Item not found", source_exc=e)

    try:
        rs_ulid = ULID.from_str(rep_spec_id.strip())
    except Exception as e:
        raise_envelope(422, "domain", "rep_spec_id is not a valid ULID", source_exc=e)

    try:
        await assign_rep_spec(session, info_item_id=item_ulid, rep_spec_id=rs_ulid)
    except AssignItemNotFoundError as e:
        raise_envelope(404, "lookup", "Information Item not found", source_exc=e)
    except RepSpecNotFoundError as e:
        raise_envelope(404, "lookup", "Replication Specification not found", source_exc=e)
    except RepFieldsIncompleteError as e:
        raise_envelope(422, "domain", "rep_fields incomplete for this RepSpec", source_exc=e)

    await session.commit()
    return RedirectResponse(
        url=f"/dashboard/info-items/{item_id}?tab=repspecs",
        status_code=303,
    )


# ---------------------------------------------------------------------------
# DELETE /{item_id}/rep-spec-assignments/{aid}
# ---------------------------------------------------------------------------


@router.delete("/{item_id}/rep-spec-assignments/{aid}")
async def deactivate_rep_spec_assignment(
    item_id: str,
    aid: str,
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    """Deactivate a RepSpec assignment (HTMX — removes row)."""
    try:
        item_ulid = ULID.from_str(item_id)
        aid_ulid = ULID.from_str(aid)
    except Exception as e:
        raise_envelope(404, "lookup", "Assignment not found", source_exc=e)

    assignment = await session.get(InfoItemRepSpec, aid_ulid)
    if assignment is None or assignment.info_item_id != item_ulid:
        raise_envelope(404, "lookup", "Assignment not found")

    assignment.deactivated_at = datetime.now(UTC)
    await session.flush()
    await session.commit()
    return Response(status_code=200)


# ---------------------------------------------------------------------------
# PATCH /{item_id}/rep-spec-assignments/{aid}/public-url
# ---------------------------------------------------------------------------


@router.patch("/{item_id}/rep-spec-assignments/{aid}/public-url", response_class=HTMLResponse)
async def set_assignment_public_url(
    request: Request,
    item_id: str,
    aid: str,
    public_url: str = Form(...),
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """Write a public URL back to a RepSpec assignment; returns an updated row fragment."""
    try:
        item_ulid = ULID.from_str(item_id)
        aid_ulid = ULID.from_str(aid)
    except Exception as e:
        raise_envelope(404, "lookup", "Assignment not found", source_exc=e)

    assignment = await session.get(InfoItemRepSpec, aid_ulid)
    if assignment is None or assignment.info_item_id != item_ulid:
        raise_envelope(404, "lookup", "Assignment not found")

    rs = await session.get(RepSpec, assignment.rep_spec_id)

    assignment.public_url = public_url.strip() or None
    await session.flush()
    await session.commit()
    await session.refresh(assignment)

    return _templates.TemplateResponse(
        request,
        "info_items/_rep_spec_row.html",
        {
            "assignment": assignment,
            "rep_spec": rs,
            "item_id": item_id,
        },
    )


# ---------------------------------------------------------------------------
# POST /{item_id}/bind-revision
# ---------------------------------------------------------------------------


@router.post("/{item_id}/bind-revision")
async def bind_revision_route(
    item_id: str,
    source_revision_id: str = Form(...),
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    """Bind a SourceRevision to this InfoItem."""
    try:
        item_ulid = ULID.from_str(item_id)
    except Exception as e:
        raise_envelope(404, "lookup", "Information Item not found", source_exc=e)

    try:
        rev_ulid = ULID.from_str(source_revision_id.strip())
    except Exception as e:
        raise_envelope(422, "domain", "source_revision_id is not a valid ULID", source_exc=e)

    try:
        await bind_revision(session, info_item_id=item_ulid, source_revision_id=rev_ulid)
    except BindRevItemNotFoundError as e:
        raise_envelope(404, "lookup", "Information Item not found", source_exc=e)
    except SourceRevisionNotFoundError as e:
        raise_envelope(404, "lookup", "Source Revision not found", source_exc=e)

    await session.commit()
    return RedirectResponse(
        url=f"/dashboard/info-items/{item_id}?tab=revisions",
        status_code=303,
    )
