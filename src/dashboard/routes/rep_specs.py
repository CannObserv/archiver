"""Dashboard — Replication Specifications (list, detail, create)."""

import json
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.api.deps import get_db_session
from src.core.models import (
    InfoItem,
    InfoItemRepSpec,
    RepSpec,
)
from src.core.tools.create_rep_spec import InvalidRepSpecError, create_rep_spec
from src.dashboard.deps import get_dashboard_user
from src.dashboard.exceptions import DashboardNotFound

router = APIRouter(prefix="/dashboard/rep-specs", tags=["dashboard-rep-specs"])

_templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

_PROVIDERS = ("gcs", "gdrive", "ia")


async def _resolve_spec(spec_id: str, session: AsyncSession) -> RepSpec:
    """Fetch RepSpec by ULID string or raise 404."""
    try:
        uid = ULID.from_str(spec_id)
    except Exception as e:
        raise DashboardNotFound("Replication Specification not found") from e
    spec = await session.get(RepSpec, uid)
    if spec is None:
        raise DashboardNotFound("Replication Specification not found")
    return spec


async def _load_active_assignments(
    spec: RepSpec, session: AsyncSession
) -> tuple[list[InfoItemRepSpec], dict[ULID, InfoItem]]:
    """Active (non-deactivated) assignments for *spec* plus their InfoItems."""
    assignment_rows = list(
        (
            await session.execute(
                select(InfoItemRepSpec).where(
                    InfoItemRepSpec.rep_spec_id == spec.rep_spec_id,
                    InfoItemRepSpec.deactivated_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    item_ids = [a.info_item_id for a in assignment_rows]
    items_by_id: dict[ULID, InfoItem] = {}
    if item_ids:
        item_rows = list(
            (await session.execute(select(InfoItem).where(InfoItem.info_item_id.in_(item_ids))))
            .scalars()
            .all()
        )
        items_by_id = {i.info_item_id: i for i in item_rows}
    return assignment_rows, items_by_id


# ---------------------------------------------------------------------------
# GET /dashboard/rep-specs/
# ---------------------------------------------------------------------------


@router.get("/", response_class=HTMLResponse)
async def list_rep_specs(
    request: Request,
    provider: str | None = None,
    limit: int = 50,
    offset: int = 0,
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """Paginated list with optional provider filter."""
    stmt = select(RepSpec).order_by(RepSpec.created_at, RepSpec.rep_spec_id)
    if provider:
        stmt = stmt.where(RepSpec.provider == provider)
    stmt = stmt.offset(offset).limit(limit + 1)

    rows = list((await session.execute(stmt)).scalars().all())
    has_more = len(rows) > limit
    rows = rows[:limit]

    return _templates.TemplateResponse(
        request,
        "rep_specs/list.html",
        {
            "user": user,
            "specs": rows,
            "has_more": has_more,
            "limit": limit,
            "offset": offset,
            "provider": provider,
            "providers": _PROVIDERS,
        },
    )


# ---------------------------------------------------------------------------
# GET /dashboard/rep-specs/new
# POST /dashboard/rep-specs/new
# ---------------------------------------------------------------------------


@router.get("/new", response_class=HTMLResponse)
async def new_rep_spec_form(
    request: Request,
    user=Depends(get_dashboard_user),
) -> HTMLResponse:
    """Render the create form."""
    return _templates.TemplateResponse(
        request,
        "rep_specs/new.html",
        {"user": user, "errors": {}, "document_raw": "", "providers": _PROVIDERS},
    )


@router.post("/new")
async def create_rep_spec_view(
    request: Request,
    provider: str = Form(default=""),
    name: str = Form(default=""),
    document: str = Form(default=""),
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Parse RepSpec JSON, create row, redirect to detail."""

    def _rerender(errors: dict) -> HTMLResponse:
        return _templates.TemplateResponse(
            request,
            "rep_specs/new.html",
            {
                "user": user,
                "errors": errors,
                "document_raw": document,
                "providers": _PROVIDERS,
                "selected_provider": provider,
                "name_value": name,
            },
        )

    if not provider:
        return _rerender({"provider": "Please select a provider."})
    if not name.strip():
        return _rerender({"name": "Name is required."})

    try:
        doc = json.loads(document) if document.strip() else {}
    except json.JSONDecodeError:
        return _rerender({"document": "Invalid JSON — could not parse."})

    try:
        spec = await create_rep_spec(session, provider=provider, name=name.strip(), document=doc)
    except InvalidRepSpecError as e:
        msg = "; ".join(str(err) for err in e.errors) if e.errors else "Invalid document."
        return _rerender({"document": msg})

    await session.commit()
    await session.refresh(spec)
    return RedirectResponse(url=f"/dashboard/rep-specs/{spec.rep_spec_id}", status_code=303)


# ---------------------------------------------------------------------------
# GET /dashboard/rep-specs/{id}
# ---------------------------------------------------------------------------


@router.get("/{spec_id}", response_class=HTMLResponse)
async def detail_rep_spec(
    spec_id: str,
    request: Request,
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """Detail: provider, name, document JSON, active assignments."""
    spec = await _resolve_spec(spec_id, session)
    assignment_rows, items_by_id = await _load_active_assignments(spec, session)

    return _templates.TemplateResponse(
        request,
        "rep_specs/detail.html",
        {
            "user": user,
            "spec": spec,
            "assignments": assignment_rows,
            "items_by_id": items_by_id,
            "doc_json": json.dumps(spec.document, indent=2),
        },
    )


# ---------------------------------------------------------------------------
# DELETE /dashboard/rep-specs/{id}/assignments/{aid}
# ---------------------------------------------------------------------------


@router.delete("/{spec_id}/assignments/{aid}", response_class=HTMLResponse)
async def deactivate_assignment(
    spec_id: str,
    aid: str,
    request: Request,
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """Deactivate a RepSpec assignment and re-render the Active Assignments section.

    Scoped to this spec (the assignment must belong to it) so a single HTMX swap
    updates the row set, the heading count, and the empty-state together. The
    InfoItem screen has its own row-level deactivate; each screen returns the
    fragment it needs.
    """
    spec = await _resolve_spec(spec_id, session)
    try:
        aid_ulid = ULID.from_str(aid)
    except Exception as e:
        raise DashboardNotFound("Assignment not found") from e

    assignment = await session.get(InfoItemRepSpec, aid_ulid)
    if assignment is None or assignment.rep_spec_id != spec.rep_spec_id:
        raise DashboardNotFound("Assignment not found")

    assignment.deactivated_at = datetime.now(UTC)
    await session.flush()
    await session.commit()

    assignment_rows, items_by_id = await _load_active_assignments(spec, session)
    return _templates.TemplateResponse(
        request,
        "rep_specs/_assignments.html",
        {
            "user": user,
            "spec": spec,
            "assignments": assignment_rows,
            "items_by_id": items_by_id,
        },
    )
