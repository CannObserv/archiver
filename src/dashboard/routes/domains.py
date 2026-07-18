"""Dashboard — Domain pages (list, detail, archive/restore, notes edit)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db_session
from src.core.models import InfoSource
from src.core.models.domain import Domain
from src.dashboard.deps import get_dashboard_user
from src.dashboard.exceptions import DashboardNotFound

router = APIRouter(prefix="/dashboard/domains", tags=["dashboard-domains"])

_templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


async def _get_domain_or_404(name: str, session: AsyncSession) -> Domain:
    result = await session.execute(select(Domain).where(Domain.name == name))
    domain = result.scalar_one_or_none()
    if domain is None:
        raise DashboardNotFound(f"Domain {name!r} not found")
    return domain


# ---------------------------------------------------------------------------
# GET /dashboard/domains/
# ---------------------------------------------------------------------------


@router.get("/", response_class=HTMLResponse)
async def list_domains(
    request: Request,
    is_active: str | None = None,
    limit: int = 50,
    offset: int = 0,
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """Paginated domain list with optional active filter."""
    stmt = select(Domain).order_by(Domain.name)
    if is_active == "true":
        stmt = stmt.where(Domain.is_active.is_(True))
    elif is_active == "false":
        stmt = stmt.where(Domain.is_active.is_(False))
    stmt = stmt.offset(offset).limit(limit + 1)

    rows = list((await session.execute(stmt)).scalars().all())
    has_more = len(rows) > limit
    rows = rows[:limit]

    # Source counts per domain in one query
    if rows:
        domain_names = [d.name for d in rows]
        counts = (
            await session.execute(
                select(InfoSource.domain_name, func.count().label("cnt"))
                .where(InfoSource.domain_name.in_(domain_names))
                .group_by(InfoSource.domain_name)
            )
        ).all()
        source_counts = {r[0]: r[1] for r in counts}
    else:
        source_counts = {}

    return _templates.TemplateResponse(
        request,
        "domains/list.html",
        {
            "user": user,
            "domains": rows,
            "source_counts": source_counts,
            "has_more": has_more,
            "limit": limit,
            "offset": offset,
            "is_active": is_active,
        },
    )


# ---------------------------------------------------------------------------
# GET /dashboard/domains/{name}
# ---------------------------------------------------------------------------


@router.get("/{name}", response_class=HTMLResponse)
async def detail_domain(
    name: str,
    request: Request,
    limit: int = 50,
    offset: int = 0,
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """Domain detail: notes, status, linked InfoSources."""
    domain = await _get_domain_or_404(name, session)

    src_rows = list(
        (
            await session.execute(
                select(InfoSource)
                .where(InfoSource.domain_name == name)
                .order_by(InfoSource.created_at.desc())
                .offset(offset)
                .limit(limit + 1)
            )
        )
        .scalars()
        .all()
    )
    has_more = len(src_rows) > limit
    src_rows = src_rows[:limit]

    # Exact total for the section heading — the table is paginated, so a template
    # `|length` would report only the current page (#82).
    source_total = (
        await session.execute(
            select(func.count()).select_from(InfoSource).where(InfoSource.domain_name == name)
        )
    ).scalar_one()

    return _templates.TemplateResponse(
        request,
        "domains/detail.html",
        {
            "user": user,
            "domain": domain,
            "sources": src_rows,
            "source_total": source_total,
            "has_more": has_more,
            "limit": limit,
            "offset": offset,
        },
    )


# ---------------------------------------------------------------------------
# POST /dashboard/domains/{name}/notes  (HTMX inline edit)
# ---------------------------------------------------------------------------


@router.post("/{name}/notes", response_class=HTMLResponse)
async def update_notes(
    name: str,
    request: Request,
    notes: str = Form(default=""),
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """HTMX: update domain notes inline, return updated notes partial."""
    domain = await _get_domain_or_404(name, session)
    domain.notes = notes.strip() or None
    await session.commit()
    await session.refresh(domain)
    return _templates.TemplateResponse(
        request,
        "domains/_notes_partial.html",
        {"user": user, "domain": domain},
    )


# ---------------------------------------------------------------------------
# POST /dashboard/domains/{name}/archive
# POST /dashboard/domains/{name}/restore
# ---------------------------------------------------------------------------


@router.post("/{name}/archive")
async def archive_domain(
    name: str,
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Archive a domain; redirect to detail."""
    domain = await _get_domain_or_404(name, session)
    domain.archived_at = datetime.now(UTC)
    await session.commit()
    return RedirectResponse(url=f"/dashboard/domains/{name}", status_code=303)


@router.post("/{name}/restore")
async def restore_domain(
    name: str,
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Restore an archived domain; redirect to detail."""
    domain = await _get_domain_or_404(name, session)
    domain.archived_at = None
    await session.commit()
    return RedirectResponse(url=f"/dashboard/domains/{name}", status_code=303)
