"""Dashboard — Information Sources (list, detail, create)."""

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
from src.api.errors import raise_envelope
from src.core.models import (
    InfoItem,
    InfoItemSource,
    InfoSource,
    SourceRevision,
)
from src.core.tools.create_info_source import (
    DuplicateUrlError,
    InvalidSourceSpecError,
    ParentMustBeRootError,
    ParentNotFoundError,
    create_info_source,
)
from src.dashboard.deps import get_dashboard_user

router = APIRouter(prefix="/dashboard/info-sources", tags=["dashboard-info-sources"])

_templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


async def _resolve_source(source_id: str, session: AsyncSession) -> InfoSource:
    """Fetch InfoSource by ULID string or raise 404."""
    try:
        uid = ULID.from_str(source_id)
    except Exception as e:
        raise_envelope(404, "lookup", "Information Source not found", source_exc=e)
    src = await session.get(InfoSource, uid)
    if src is None:
        raise_envelope(404, "lookup", "Information Source not found")
    return src


# ---------------------------------------------------------------------------
# GET /dashboard/info-sources/
# ---------------------------------------------------------------------------


@router.get("/", response_class=HTMLResponse)
async def list_info_sources(
    request: Request,
    shape: str | None = None,
    url_contains: str | None = None,
    limit: int = 50,
    offset: int = 0,
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """Paginated list with optional shape and URL filters."""
    stmt = select(InfoSource).order_by(InfoSource.created_at, InfoSource.info_source_id)
    if shape == "root":
        stmt = stmt.where(InfoSource.parent_info_source_id.is_(None))
    elif shape == "fragment":
        stmt = stmt.where(InfoSource.parent_info_source_id.is_not(None))
    if url_contains:
        stmt = stmt.where(InfoSource.url.ilike(f"%{url_contains}%"))
    stmt = stmt.offset(offset).limit(limit + 1)

    rows = list((await session.execute(stmt)).scalars().all())
    has_more = len(rows) > limit
    rows = rows[:limit]

    return _templates.TemplateResponse(
        request,
        "info_sources/list.html",
        {
            "user": user,
            "sources": rows,
            "has_more": has_more,
            "limit": limit,
            "offset": offset,
            "shape": shape,
            "url_contains": url_contains,
        },
    )


# ---------------------------------------------------------------------------
# GET /dashboard/info-sources/new
# POST /dashboard/info-sources/new
# ---------------------------------------------------------------------------


@router.get("/new", response_class=HTMLResponse)
async def new_info_source_form(
    request: Request,
    user=Depends(get_dashboard_user),
) -> HTMLResponse:
    """Render the create form."""
    return _templates.TemplateResponse(
        request,
        "info_sources/new.html",
        {"user": user, "errors": {}, "source_spec_raw": ""},
    )


@router.post("/new")
async def create_info_source_view(
    request: Request,
    source_spec: str = Form(default=""),
    parent_info_source_id: str = Form(default=""),
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Parse SourceSpec JSON, create row, redirect to detail."""

    def _rerender(errors: dict, conflict_id: str | None = None) -> HTMLResponse:
        return _templates.TemplateResponse(
            request,
            "info_sources/new.html",
            {
                "user": user,
                "errors": errors,
                "source_spec_raw": source_spec,
                "conflict_id": conflict_id,
            },
        )

    try:
        spec_doc = json.loads(source_spec) if source_spec.strip() else {}
    except json.JSONDecodeError:
        return _rerender({"source_spec": "Invalid JSON — could not parse."})

    parent_ulid: ULID | None = None
    if parent_info_source_id.strip():
        try:
            parent_ulid = ULID.from_str(parent_info_source_id.strip())
        except Exception:
            return _rerender({"parent_info_source_id": "Not a valid ULID."})

    try:
        src = await create_info_source(
            session, source_spec=spec_doc, parent_info_source_id=parent_ulid
        )
    except InvalidSourceSpecError as e:
        msg = "; ".join(str(err) for err in e.errors) if e.errors else "Invalid source spec."
        return _rerender({"source_spec": msg})
    except ParentNotFoundError:
        return _rerender({"parent_info_source_id": "Parent Information Source not found."})
    except ParentMustBeRootError:
        return _rerender({"parent_info_source_id": "Parent must be a root Information Source."})
    except DuplicateUrlError as e:
        return _rerender(
            {"source_spec": "An Information Source with this URL already exists."},
            conflict_id=str(e.existing_info_source_id),
        )

    await session.commit()
    await session.refresh(src)
    return RedirectResponse(
        url=f"/dashboard/info-sources/{src.info_source_id}",
        status_code=303,
    )


# ---------------------------------------------------------------------------
# GET /dashboard/info-sources/{id}
# ---------------------------------------------------------------------------


@router.get("/{source_id}", response_class=HTMLResponse)
async def detail_info_source(
    source_id: str,
    request: Request,
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """Detail page: spec, parent link, bound items, revisions."""
    src = await _resolve_source(source_id, session)

    # Parent (if fragment)
    parent: InfoSource | None = None
    if src.parent_info_source_id is not None:
        parent = await session.get(InfoSource, src.parent_info_source_id)

    # Active bindings → InfoItems
    binding_rows = list(
        (
            await session.execute(
                select(InfoItemSource).where(
                    InfoItemSource.info_source_id == src.info_source_id,
                    InfoItemSource.deactivated_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    item_ids = [b.info_item_id for b in binding_rows]
    items_by_id: dict[ULID, InfoItem] = {}
    if item_ids:
        item_rows = list(
            (await session.execute(select(InfoItem).where(InfoItem.info_item_id.in_(item_ids))))
            .scalars()
            .all()
        )
        items_by_id = {i.info_item_id: i for i in item_rows}

    # Revisions
    revision_rows = list(
        (
            await session.execute(
                select(SourceRevision)
                .where(SourceRevision.info_source_id == src.info_source_id)
                .order_by(SourceRevision.captured_at.desc())
                .limit(50)
            )
        )
        .scalars()
        .all()
    )

    return _templates.TemplateResponse(
        request,
        "info_sources/detail.html",
        {
            "user": user,
            "src": src,
            "parent": parent,
            "bindings": binding_rows,
            "items_by_id": items_by_id,
            "revisions": revision_rows,
            "spec_json": json.dumps(src.source_spec, indent=2),
            "now": datetime.now(UTC),
        },
    )
