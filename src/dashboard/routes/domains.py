"""Dashboard — Domain pages (list, detail, archive/restore, notes edit)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db_session
from src.core.models import InfoItem, InfoItemSource, InfoSource
from src.core.models.domain import Domain
from src.dashboard.deps import get_dashboard_user
from src.dashboard.exceptions import DashboardNotFound
from src.dashboard.pagination import Pagination, clamp_pagination, pagination

router = APIRouter(prefix="/dashboard/domains")

_templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

_ITEM_LIMIT_DESCRIPTION = (
    "Rows per page for the Information Items table. Clamped, not rejected — see "
    "src/dashboard/pagination.py."
)
_ITEM_OFFSET_DESCRIPTION = (
    "Row offset for the Information Items table. Clamped, not rejected — see "
    "src/dashboard/pagination.py."
)


async def item_pagination(
    item_limit: str | None = Query(default=None, description=_ITEM_LIMIT_DESCRIPTION),
    item_offset: str | None = Query(default=None, description=_ITEM_OFFSET_DESCRIPTION),
) -> Pagination:
    """Second, independent page window for the detail screen's Items table.

    Domain detail renders two paginated tables. Sharing one ``limit``/``offset``
    pair would make paging either table silently reposition the other, so Items
    gets its own params and Sources keeps the bare ones. Same clamp-don't-reject
    contract as ``pagination`` — see ``src/dashboard/pagination.py`` for why
    these arrive as ``str``.
    """
    return clamp_pagination(item_limit, item_offset)


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
    page: Pagination = Depends(pagination),
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """Paginated domain list with optional active filter."""
    stmt = select(Domain).order_by(Domain.name)
    if is_active == "true":
        stmt = stmt.where(Domain.is_active.is_(True))
    elif is_active == "false":
        stmt = stmt.where(Domain.is_active.is_(False))
    stmt = stmt.offset(page.offset).limit(page.limit + 1)

    rows = list((await session.execute(stmt)).scalars().all())
    has_more = len(rows) > page.limit
    rows = rows[: page.limit]

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
            "limit": page.limit,
            "offset": page.offset,
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
    page: Pagination = Depends(pagination),
    item_page: Pagination = Depends(item_pagination),
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """Domain detail: notes, status, linked InfoItems and InfoSources."""
    domain = await _get_domain_or_404(name, session)

    # Exact total for the section heading — the table is paginated, so a template
    # `|length` would report only the current page (#82).
    source_total = (
        await session.execute(
            select(func.count()).select_from(InfoSource).where(InfoSource.domain_name == name)
        )
    ).scalar_one()

    # `has_more` deliberately does NOT derive from source_total. The limit+1 probe
    # is self-consistent by construction — one statement, one snapshot — so the
    # Next link always matches the rows actually rendered. Deriving it from the
    # COUNT would compare across two statements (two READ COMMITTED snapshots),
    # letting a concurrent delete produce a Next link into an empty page. The two
    # values answer different questions; the redundancy is intentional (CR round 8).
    src_rows = list(
        (
            await session.execute(
                select(InfoSource)
                .where(InfoSource.domain_name == name)
                .order_by(InfoSource.created_at.desc())
                .offset(page.offset)
                .limit(page.limit + 1)
            )
        )
        .scalars()
        .all()
    )
    has_more = len(src_rows) > page.limit
    src_rows = src_rows[: page.limit]

    # Items reachable from this domain: InfoItem → active InfoItemSource →
    # InfoSource.domain_name. `deactivated_at IS NULL` keeps a superseded primary
    # out — that binding is succession history, not a current dependency on this
    # domain (see src/core/models/info_item_source.py).
    #
    # A semi-join (IN over the binding table), not a join onto InfoItem. Joining
    # would multiply an item by its matching bindings and need DISTINCT to put it
    # back — and DISTINCT here means deduplicating whole InfoItem rows, `rep_fields`
    # and `watch_spec` JSONB payloads included, on every render. The semi-join
    # cannot produce a duplicate in the first place, so it stays correct if the
    # one-active-binding-per-item invariant is ever relaxed, without paying for the
    # dedup while it holds.
    items_on_domain = (
        select(InfoItemSource.info_item_id)
        .join(InfoSource, InfoSource.info_source_id == InfoItemSource.info_source_id)
        .where(
            InfoSource.domain_name == name,
            InfoItemSource.deactivated_at.is_(None),
        )
    )
    # Bound once: the count and the page must ask the same question, and nothing
    # else enforces that they do.
    on_domain = InfoItem.info_item_id.in_(items_on_domain)
    item_query = select(InfoItem).where(on_domain)

    item_total = (
        await session.execute(select(func.count()).select_from(InfoItem).where(on_domain))
    ).scalar_one()

    # Own limit+1 probe rather than a comparison against item_total, for the same
    # cross-snapshot reason spelled out above the sources probe.
    item_rows = list(
        (
            await session.execute(
                item_query.order_by(InfoItem.created_at.desc(), InfoItem.info_item_id.desc())
                .offset(item_page.offset)
                .limit(item_page.limit + 1)
            )
        )
        .scalars()
        .all()
    )
    item_has_more = len(item_rows) > item_page.limit
    item_rows = item_rows[: item_page.limit]

    return _templates.TemplateResponse(
        request,
        "domains/detail.html",
        {
            "user": user,
            "domain": domain,
            "sources": src_rows,
            "source_total": source_total,
            "has_more": has_more,
            "limit": page.limit,
            "offset": page.offset,
            "items": item_rows,
            "item_total": item_total,
            "item_has_more": item_has_more,
            "item_limit": item_page.limit,
            "item_offset": item_page.offset,
        },
    )


# ---------------------------------------------------------------------------
# POST /dashboard/domains/{name}/notes  (HTMX inline edit)
# ---------------------------------------------------------------------------


@router.post("/{name}/notes")
async def update_notes(
    name: str,
    request: Request,
    notes: str = Form(default=""),
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    """Update domain notes.

    HTMX requests get the re-rendered ``_notes_partial.html`` swapped in place,
    in read-only mode, with an ``HX-Trigger: showFlash`` toast and focus moved to
    the heading. Non-HTMX requests — the operator submitting the same form with
    JS off — get the plain POST→303 back to detail, so the fallback the form
    declares actually lands somewhere rather than rendering a bare fragment as a
    whole page. Branching on the header, not the target, per
    docs/SCREENS.md.

    Notes have no validation-error path: any string is a legal note, and an
    empty one clears the field.
    """
    domain = await _get_domain_or_404(name, session)
    domain.notes = notes.strip() or None
    await session.commit()
    await session.refresh(domain)

    if not request.headers.get("HX-Request"):
        return RedirectResponse(url=f"/dashboard/domains/{name}", status_code=303)

    response = _templates.TemplateResponse(
        request,
        "domains/_notes_partial.html",
        # `swapped` gates the focus-move script — emitted only for the swap.
        {"user": user, "domain": domain, "swapped": True},
    )
    response.headers["HX-Trigger"] = json.dumps(
        {"showFlash": {"level": "success", "body": "Notes updated."}}
    )
    return response


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
