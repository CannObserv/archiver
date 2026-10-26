"""Dashboard — Domain pages (list, detail, archive/restore, notes and fetch-policy edit)."""

from __future__ import annotations

import json
import math
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
from src.core.services.domain_policy import update_domain
from src.core.services.fetch_policy import producer_enabled
from src.core.services.registry_announcement import domain_suspended
from src.core.watch_spec_schema.validator import validate_domain_watch_spec
from src.dashboard.cadence import CADENCE_LABELS, CADENCE_OPTIONS
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
                .order_by(InfoSource.created_at.desc(), InfoSource.info_source_id.desc())
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
            "cadence_labels": CADENCE_LABELS,
            "stored_interval": _stored_interval(domain),
            "fetch_policy_live": producer_enabled(),
            "suspended": domain_suspended(domain),
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
# POST /dashboard/domains/{name}/fetch-policy  (HTMX inline save, archiver#360)
# ---------------------------------------------------------------------------


def _stored_interval(domain: Domain) -> str | None:
    """The stored cadence's ``interval``, or ``None``.

    Tolerates a hand-edited non-object ``default_watch_spec`` (CR 18): the
    stored-document sweep flags it, and this page is where it gets fixed, so it
    must not 500 here.
    """
    spec = domain.default_watch_spec
    interval = spec.get("interval") if isinstance(spec, dict) else None
    return interval if isinstance(interval, str) else None


def _policy_refusal(domain: Domain, min_interval_seconds: str, default_interval: str) -> str | None:
    """Why the posted policy is refused, or ``None`` when it may be stored.

    The cadence is held to the dashboard's vocabulary, like the item cadence
    editor, except that the interval already stored passes: an imported or
    API-set value must not strand the operator on re-save. The API takes the
    full grammar.
    """
    try:
        seconds = float(min_interval_seconds)
    except ValueError:
        return "The minimum interval must be a number of seconds."
    if not math.isfinite(seconds) or seconds < 0:
        return "The minimum interval must be a finite number of seconds, 0 or more."
    stored = _stored_interval(domain)
    if default_interval and default_interval not in CADENCE_OPTIONS and default_interval != stored:
        return f"“{default_interval}” is not one of the offered cadences."
    if default_interval:
        ok, _errors = validate_domain_watch_spec(
            {"schema_version": 1, "interval": default_interval}
        )
        if not ok:
            return f"“{default_interval}” is not a valid interval."
    return None


@router.post("/{name}/fetch-policy")
async def update_fetch_policy(
    name: str,
    request: Request,
    min_interval_seconds: str = Form(default=""),
    default_interval: str = Form(default=""),
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    """Store the host's minimum interval (live since F1) and default cadence (dark until F2).

    An empty ``default_interval`` clears the cadence. HTMX requests get the
    re-rendered ``_policy_partial.html`` and a toast, success or refusal; a
    refusal writes nothing. Non-HTMX requests get POST→303 back to detail, the
    notes row's fallback - a refusal is then silent (the page shows the stored
    values), the price of a no-JS path on an operator screen.
    """
    domain = await _get_domain_or_404(name, session)
    refusal = _policy_refusal(domain, min_interval_seconds.strip(), default_interval.strip())
    if refusal is None:
        interval = default_interval.strip()
        domain = await update_domain(
            session,
            name,
            {
                "min_interval_seconds": float(min_interval_seconds),
                "default_watch_spec": (
                    {"schema_version": 1, "interval": interval} if interval else None
                ),
            },
            create=False,
        )
        if domain is None:  # deleted since the read above (CR 4)
            raise DashboardNotFound(f"Domain {name!r} not found")
        await session.commit()
        await session.refresh(domain)

    if not request.headers.get("HX-Request"):
        return RedirectResponse(url=f"/dashboard/domains/{name}", status_code=303)

    response = _templates.TemplateResponse(
        request,
        "domains/_policy_partial.html",
        {
            "user": user,
            "domain": domain,
            "cadence_labels": CADENCE_LABELS,
            "stored_interval": _stored_interval(domain),
            "fetch_policy_live": producer_enabled(),
            "swapped": True,
        },
    )
    flash = (
        {"level": "success", "body": "Fetch policy saved."}
        if refusal is None
        else {"level": "error", "body": refusal}
    )
    response.headers["HX-Trigger"] = json.dumps({"showFlash": flash})
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
    """Archive a domain, suspending its host (archiver#360); redirect to detail."""
    await _get_domain_or_404(name, session)
    await update_domain(session, name, {"archived_at": datetime.now(UTC)}, create=False)
    await session.commit()
    return RedirectResponse(url=f"/dashboard/domains/{name}", status_code=303)


@router.post("/{name}/restore")
async def restore_domain(
    name: str,
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Restore an archived domain, resuming its host unless inactive; redirect to detail."""
    await _get_domain_or_404(name, session)
    await update_domain(session, name, {"archived_at": None}, create=False)
    await session.commit()
    return RedirectResponse(url=f"/dashboard/domains/{name}", status_code=303)
