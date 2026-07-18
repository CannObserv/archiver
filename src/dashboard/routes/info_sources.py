"""Dashboard — Information Sources (list, detail, create, edit specs)."""

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
    InfoItemSource,
    InfoSource,
    SourceRevision,
)
from src.core.tools.create_info_source import (
    CreateInfoSourceError,
    InvalidSourceSpecError,
    InvalidUrlError,
    MixedAlgorithmFamilyError,
    create_info_source,
)
from src.core.tools.update_info_source_specs import (
    InvalidSourceSpecError as UpdateInvalidSpecError,
)
from src.core.tools.update_info_source_specs import (
    MixedAlgorithmFamilyError as UpdateMixedFamilyError,
)
from src.core.tools.update_info_source_specs import (
    update_info_source_specs,
)
from src.dashboard.deps import get_dashboard_user
from src.dashboard.exceptions import DashboardNotFound

router = APIRouter(prefix="/dashboard/info-sources", tags=["dashboard-info-sources"])

_templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


async def _resolve_source(source_id: str, session: AsyncSession) -> InfoSource:
    """Fetch InfoSource by ULID string or raise 404."""
    try:
        uid = ULID.from_str(source_id)
    except Exception as e:
        raise DashboardNotFound("Information Source not found") from e
    src = await session.get(InfoSource, uid)
    if src is None:
        raise DashboardNotFound("Information Source not found")
    return src


_SIBLING_DISPLAY_LIMIT = 50


async def _detail_context(
    src: InfoSource,
    user,
    session: AsyncSession,
    *,
    specs_error: str | None = None,
    specs_input: str | None = None,
) -> dict:
    """Build the template context dict for the InfoSource detail page."""
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
    # limit+1 probe so the heading can show "50+" rather than a misleading exact
    # count when more sources share this URL than we display.
    sibling_rows = list(
        (
            await session.execute(
                select(InfoSource)
                .where(
                    InfoSource.url == src.url,
                    InfoSource.info_source_id != src.info_source_id,
                )
                .order_by(InfoSource.created_at, InfoSource.info_source_id)
                .limit(_SIBLING_DISPLAY_LIMIT + 1)
            )
        )
        .scalars()
        .all()
    )
    siblings_has_more = len(sibling_rows) > _SIBLING_DISPLAY_LIMIT
    sibling_rows = sibling_rows[:_SIBLING_DISPLAY_LIMIT]
    return {
        "user": user,
        "src": src,
        "bindings": binding_rows,
        "items_by_id": items_by_id,
        "revisions": revision_rows,
        "siblings": sibling_rows,
        "siblings_has_more": siblings_has_more,
        "specs_json": json.dumps(src.source_specs, indent=2),
        "specs_input": specs_input,
        "now": datetime.now(UTC),
        "specs_error": specs_error,
    }


# ---------------------------------------------------------------------------
# GET /dashboard/info-sources/
# ---------------------------------------------------------------------------


@router.get("/", response_class=HTMLResponse)
async def list_info_sources(
    request: Request,
    url_contains: str | None = None,
    limit: int = 50,
    offset: int = 0,
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """Paginated list with optional URL filter."""
    stmt = select(InfoSource).order_by(InfoSource.created_at, InfoSource.info_source_id)
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
        {"user": user, "errors": {}, "url_value": "", "source_specs_raw": ""},
    )


@router.post("/new")
async def create_info_source_view(
    request: Request,
    url: str = Form(default=""),
    source_specs: str = Form(default=""),
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Parse URL + source_specs JSON array, create row, redirect to detail."""

    def _rerender(errors: dict) -> HTMLResponse:
        return _templates.TemplateResponse(
            request,
            "info_sources/new.html",
            {
                "user": user,
                "errors": errors,
                "url_value": url,
                "source_specs_raw": source_specs,
            },
        )

    url_val = url.strip()
    if not url_val:
        return _rerender({"url": "URL is required."})

    try:
        specs_list = json.loads(source_specs) if source_specs.strip() else []
        if not isinstance(specs_list, list):
            return _rerender({"source_specs": "Must be a JSON array."})
    except json.JSONDecodeError:
        return _rerender({"source_specs": "Invalid JSON — could not parse."})

    try:
        src = await create_info_source(session, url=url_val, source_specs=specs_list)
    except InvalidUrlError as e:
        return _rerender({"url": str(e)})
    except InvalidSourceSpecError as e:
        msg = "; ".join(err.get("message", "") for err in e.errors) if e.errors else str(e)
        return _rerender({"source_specs": msg})
    except MixedAlgorithmFamilyError as e:
        return _rerender({"source_specs": str(e)})
    except CreateInfoSourceError as e:
        return _rerender({"source_specs": str(e)})

    await session.commit()
    await session.refresh(src)
    return RedirectResponse(
        url=f"/dashboard/info-sources/{src.info_source_id}",
        status_code=303,
    )


# ---------------------------------------------------------------------------
# GET /dashboard/info-sources/{id}
# POST /dashboard/info-sources/{id}/source-specs (update specs)
# ---------------------------------------------------------------------------


@router.get("/{source_id}", response_class=HTMLResponse)
async def detail_info_source(
    source_id: str,
    request: Request,
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """Detail page: URL, specs, bound items, revisions."""
    src = await _resolve_source(source_id, session)
    ctx = await _detail_context(src, user, session)
    return _templates.TemplateResponse(request, "info_sources/detail.html", ctx)


@router.post("/{source_id}/source-specs")
async def update_info_source_specs_view(
    source_id: str,
    request: Request,
    source_specs: str = Form(default=""),
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Replace source_specs on an existing InfoSource.

    HTMX requests (``HX-Request``) get the re-rendered ``_source_specs_card.html``
    partial swapped in place: success carries an ``HX-Trigger: showFlash`` toast;
    a validation error swaps the card back with an inline error (status 200 so
    htmx performs the swap) that is announced (``role="alert"``), moves focus to
    the heading, and preserves the operator's submitted text. Non-HTMX requests
    keep the plain full-page POST→303 (success) / 422 re-render (error, also
    preserving submitted text) fallback (progressive enhancement). See docs/UI.md
    Detail Screen Conventions.
    """
    src = await _resolve_source(source_id, session)
    is_htmx = bool(request.headers.get("HX-Request"))

    async def _rerender(error: str) -> HTMLResponse:
        if is_htmx:
            # 200 so htmx swaps the card; inline error stays visible. Echo the
            # submitted text back (specs_input) so the operator's edit isn't lost,
            # move focus to the heading, and role="alert" announces the error.
            return _templates.TemplateResponse(
                request,
                "info_sources/_source_specs_card.html",
                {
                    "src": src,
                    "specs_json": json.dumps(src.source_specs, indent=2),
                    "specs_input": source_specs,
                    "specs_error": error,
                    "swapped": True,
                },
            )
        ctx = await _detail_context(src, user, session, specs_error=error, specs_input=source_specs)
        return _templates.TemplateResponse(
            request, "info_sources/detail.html", ctx, status_code=422
        )

    try:
        specs_list = json.loads(source_specs) if source_specs.strip() else []
        if not isinstance(specs_list, list):
            raise ValueError("not a list")
    except (json.JSONDecodeError, ValueError):
        return await _rerender("source_specs must be a JSON array")

    try:
        await update_info_source_specs(
            session, info_source_id=src.info_source_id, source_specs=specs_list
        )
    except UpdateInvalidSpecError as e:
        return await _rerender(
            "; ".join(err.get("message", "") for err in e.errors) if e.errors else str(e)
        )
    except UpdateMixedFamilyError as e:
        return await _rerender(str(e))

    await session.commit()

    if is_htmx:
        await session.refresh(src)
        response = _templates.TemplateResponse(
            request,
            "info_sources/_source_specs_card.html",
            {
                "src": src,
                "specs_json": json.dumps(src.source_specs, indent=2),
                "specs_error": None,
                "swapped": True,
            },
        )
        response.headers["HX-Trigger"] = json.dumps(
            {"showFlash": {"level": "success", "body": "Source specs updated."}}
        )
        return response

    return RedirectResponse(
        url=f"/dashboard/info-sources/{source_id}",
        status_code=303,
    )
