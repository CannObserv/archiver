"""Dashboard — Information Source Revisions (list, detail, cache-clear)."""

import json
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.api.deps import get_db_session
from src.core.models import (
    InfoSource,
    SourceRevision,
)
from src.dashboard.deps import get_dashboard_user
from src.dashboard.exceptions import DashboardNotFound
from src.dashboard.pagination import Pagination, pagination

router = APIRouter(prefix="/dashboard/source-revisions")

_templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


async def _resolve_revision(rev_id: str, session: AsyncSession) -> SourceRevision:
    """Fetch SourceRevision by ULID string or raise 404."""
    try:
        uid = ULID.from_str(rev_id)
    except Exception as e:
        raise DashboardNotFound("Information Source Revision not found") from e
    rev = await session.get(SourceRevision, uid)
    if rev is None:
        raise DashboardNotFound("Information Source Revision not found")
    return rev


# ---------------------------------------------------------------------------
# GET /dashboard/source-revisions/
# ---------------------------------------------------------------------------


@router.get("/", response_class=HTMLResponse)
async def list_source_revisions(
    request: Request,
    info_source_id: str | None = None,
    page: Pagination = Depends(pagination),
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """Paginated list; optional filter by info_source_id."""
    stmt = select(SourceRevision).order_by(
        SourceRevision.captured_at.desc(), SourceRevision.source_revision_id
    )
    filter_source: InfoSource | None = None
    if info_source_id:
        try:
            src_ulid = ULID.from_str(info_source_id)
        except Exception:
            src_ulid = None
        if src_ulid is not None:
            filter_source = await session.get(InfoSource, src_ulid)
            stmt = stmt.where(SourceRevision.info_source_id == src_ulid)
    stmt = stmt.offset(page.offset).limit(page.limit + 1)

    rows = list((await session.execute(stmt)).scalars().all())
    has_more = len(rows) > page.limit
    rows = rows[: page.limit]

    # Batch-load InfoSources for display
    source_ids = list({r.info_source_id for r in rows})
    sources_by_id: dict[ULID, InfoSource] = {}
    if source_ids:
        src_rows = list(
            (
                await session.execute(
                    select(InfoSource).where(InfoSource.info_source_id.in_(source_ids))
                )
            )
            .scalars()
            .all()
        )
        sources_by_id = {s.info_source_id: s for s in src_rows}

    now = datetime.now(UTC)
    return _templates.TemplateResponse(
        request,
        "source_revisions/list.html",
        {
            "user": user,
            "revisions": rows,
            "sources_by_id": sources_by_id,
            "filter_source": filter_source,
            "info_source_id": info_source_id,
            "has_more": has_more,
            "limit": page.limit,
            "offset": page.offset,
            "now": now,
        },
    )


# ---------------------------------------------------------------------------
# GET /dashboard/source-revisions/{id}
# ---------------------------------------------------------------------------


@router.get("/{rev_id}", response_class=HTMLResponse)
async def detail_source_revision(
    rev_id: str,
    request: Request,
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """Detail: fingerprint, source link, cache info."""
    rev = await _resolve_revision(rev_id, session)

    source = await session.get(InfoSource, rev.info_source_id)

    now = datetime.now(UTC)
    return _templates.TemplateResponse(
        request,
        "source_revisions/detail.html",
        {
            "user": user,
            "rev": rev,
            "source": source,
            "now": now,
        },
    )


# ---------------------------------------------------------------------------
# POST /dashboard/source-revisions/{id}/clear-cache
# ---------------------------------------------------------------------------


@router.post("/{rev_id}/clear-cache")
async def clear_revision_cache(
    rev_id: str,
    request: Request,
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Clear content_cache_uri and content_cache_expires_at.

    HTMX requests get the re-rendered header card swapped in place plus a
    ``showFlash`` success toast (archiver#73). Non-HTMX requests (JS disabled)
    fall back to a 303 redirect to the detail page.
    """
    rev = await _resolve_revision(rev_id, session)
    rev.content_cache_uri = None
    rev.content_cache_expires_at = None
    await session.commit()

    if request.headers.get("HX-Request"):
        source = await session.get(InfoSource, rev.info_source_id)
        response = _templates.TemplateResponse(
            request,
            "source_revisions/_detail_card.html",
            {
                "user": user,
                "rev": rev,
                "source": source,
                "now": datetime.now(UTC),
                "swapped": True,
            },
        )
        response.headers["HX-Trigger"] = json.dumps(
            {"showFlash": {"level": "success", "body": "Cache fields cleared."}}
        )
        return response

    return RedirectResponse(
        url=f"/dashboard/source-revisions/{rev.source_revision_id}",
        status_code=303,
    )
