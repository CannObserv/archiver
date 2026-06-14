"""Dashboard — Information Items (list, detail, create, sub-resource mutations)."""

import json
import os
import re
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from html import escape as html_escape
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.api.deps import get_db_session, get_watcher_client
from src.api.errors import raise_envelope
from src.core.watcher_provisioning import provision_on_create, sync_on_source_swap

if TYPE_CHECKING:
    from watcher_client import WatchedItemResponse, WatcherClient

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
from src.core.url_canonicalization import canonicalize_url
from src.dashboard.cadence import CADENCE_LABELS
from src.dashboard.deps import get_dashboard_user
from src.dashboard.exceptions import DashboardNotFound

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
        raise DashboardNotFound("Information Item not found") from e
    item = await session.get(InfoItem, uid)
    if item is None:
        raise DashboardNotFound("Information Item not found")
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


@router.get("/new")
async def new_info_item_form(
    request: Request,
    user=Depends(get_dashboard_user),
) -> RedirectResponse:
    """301 redirect to the new /dashboard/register flow."""
    return RedirectResponse(url="/dashboard/register", status_code=301)


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
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """InfoItem hub page — 5-section vertical scroll."""
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
        },
    )


# ---------------------------------------------------------------------------
# GET /{item_id}/suggest-rep-fields  (HTMX partial — #49)
# ---------------------------------------------------------------------------


@router.get("/{item_id}/suggest-rep-fields", response_class=HTMLResponse)
async def suggest_rep_fields(
    item_id: str,
    request: Request,
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """HTMX partial: domain-scoped rep_fields key suggestions as sortableChips."""
    item = await _resolve_item(item_id, session)

    # Query 1: derive domain_name from the item's active primary source.
    domain_name: str | None = (
        await session.execute(
            select(InfoSource.domain_name).join(
                InfoItemSource,
                (InfoItemSource.info_source_id == InfoSource.info_source_id)
                & (InfoItemSource.info_item_id == item.info_item_id)
                & InfoItemSource.deactivated_at.is_(None),
            )
        )
    ).scalar_one_or_none()

    suggestions: list[dict] = []
    if domain_name:
        # Query 2: rep_fields of all actively-bound items sharing the same domain.
        rep_fields_rows = list(
            (
                await session.execute(
                    select(InfoItem.rep_fields)
                    .join(
                        InfoItemSource,
                        (InfoItemSource.info_item_id == InfoItem.info_item_id)
                        & InfoItemSource.deactivated_at.is_(None),
                    )
                    .join(
                        InfoSource,
                        (InfoSource.info_source_id == InfoItemSource.info_source_id)
                        & (InfoSource.domain_name == domain_name),
                    )
                )
            )
            .scalars()
            .all()
        )
        key_counter: Counter = Counter()
        for rep_fields in rep_fields_rows:
            for k in (rep_fields or {}).keys():
                key_counter[k] += 1
        for key, freq in key_counter.most_common():
            suggestions.append({"label": key, "frequency": freq})

    return _templates.TemplateResponse(
        request,
        "info_items/_rep_fields_suggestions.html",
        {"user": user, "suggestions": suggestions},
    )


# ---------------------------------------------------------------------------
# PATCH /{item_id}/rep-fields  (inline save — #49)
# ---------------------------------------------------------------------------


@router.patch("/{item_id}/rep-fields", response_class=HTMLResponse)
async def patch_rep_fields(
    item_id: str,
    request: Request,
    rep_fields: str = Form(default="{}"),
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """HTMX: save rep_fields JSON inline; return updated section partial."""
    item = await _resolve_item(item_id, session)

    try:
        parsed = json.loads(rep_fields) if rep_fields.strip() else {}
        if not isinstance(parsed, dict):
            raise ValueError("rep_fields must be a JSON object")
    except (json.JSONDecodeError, ValueError) as exc:
        return HTMLResponse(
            f'<p class="text-danger text-sm">Invalid rep_fields: {html_escape(str(exc))}</p>',
            status_code=422,
        )

    item.rep_fields = parsed
    await session.commit()
    await session.refresh(item)

    return HTMLResponse(
        '<p class="badge badge--success" style="margin-top:var(--space-1);">Saved.</p>'
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
        raise DashboardNotFound("Information Item not found") from e

    try:
        source_ulid = ULID.from_str(info_source_id)
    except Exception as e:
        raise_envelope(422, "domain", "info_source_id is not a valid ULID", source_exc=e)

    try:
        await bind_info_source(session, info_item_id=item_ulid, info_source_id=source_ulid)
    except BindItemNotFoundError as e:
        raise DashboardNotFound("Information Item not found") from e
    except BindSourceNotFoundError as e:
        raise DashboardNotFound("Information Source not found") from e
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
        raise DashboardNotFound("Binding not found") from e

    try:
        await deactivate_info_item_source_binding(
            session, info_item_id=item_ulid, info_source_id=source_ulid
        )
    except BindingNotFoundError as e:
        raise DashboardNotFound("Active binding not found") from e

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
        raise DashboardNotFound("Information Item not found") from e

    try:
        rs_ulid = ULID.from_str(rep_spec_id.strip())
    except Exception as e:
        raise_envelope(422, "domain", "rep_spec_id is not a valid ULID", source_exc=e)

    try:
        await assign_rep_spec(session, info_item_id=item_ulid, rep_spec_id=rs_ulid)
    except AssignItemNotFoundError as e:
        raise DashboardNotFound("Information Item not found") from e
    except RepSpecNotFoundError as e:
        raise DashboardNotFound("Replication Specification not found") from e
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
        raise DashboardNotFound("Assignment not found") from e

    assignment = await session.get(InfoItemRepSpec, aid_ulid)
    if assignment is None or assignment.info_item_id != item_ulid:
        raise DashboardNotFound("Assignment not found")

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
        raise DashboardNotFound("Assignment not found") from e

    assignment = await session.get(InfoItemRepSpec, aid_ulid)
    if assignment is None or assignment.info_item_id != item_ulid:
        raise DashboardNotFound("Assignment not found")

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
        raise DashboardNotFound("Information Item not found") from e

    try:
        rev_ulid = ULID.from_str(source_revision_id.strip())
    except Exception as e:
        raise_envelope(422, "domain", "source_revision_id is not a valid ULID", source_exc=e)

    try:
        await bind_revision(session, info_item_id=item_ulid, source_revision_id=rev_ulid)
    except BindRevItemNotFoundError as e:
        raise DashboardNotFound("Information Item not found") from e
    except SourceRevisionNotFoundError as e:
        raise DashboardNotFound("Source Revision not found") from e

    await session.commit()
    return RedirectResponse(
        url=f"/dashboard/info-items/{item_id}?tab=revisions",
        status_code=303,
    )


# ---------------------------------------------------------------------------
# POST /{item_id}/swap-primary-source
# ---------------------------------------------------------------------------


@router.post("/{item_id}/swap-primary-source")
async def swap_primary_source(
    item_id: str,
    request: Request,
    url: str = Form(default=""),
    source_specs: str = Form(default="[]"),
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
    watcher: "WatcherClient | None" = Depends(get_watcher_client),
) -> Response:
    """Author new InfoSource inline, deactivate old primary binding, bind new source.

    Best-effort Watcher patch follows commit if watcher_item_id is set.
    """
    item = await _resolve_item(item_id, session)

    try:
        canonical_url = canonicalize_url(url)
    except ValueError as exc:
        return HTMLResponse(
            f'<div id="swap-error" role="alert" aria-live="polite" aria-atomic="true">'
            f'<p class="text-danger">Invalid URL: {html_escape(str(exc))}</p>'
            "</div>",
            status_code=422,
        )

    try:
        specs = json.loads(source_specs) if source_specs.strip() else []
        if not isinstance(specs, list):
            raise ValueError("must be a JSON array")
    except (json.JSONDecodeError, ValueError) as exc:
        return HTMLResponse(
            f'<div id="swap-error" role="alert" aria-live="polite" aria-atomic="true">'
            f'<p class="text-danger">Invalid source specs: {html_escape(str(exc))}</p>'
            "</div>",
            status_code=422,
        )

    try:
        new_src = await create_info_source(session, url=canonical_url, source_specs=specs)
    except (
        InvalidUrlError,
        InvalidSourceSpecError,
        MixedAlgorithmFamilyError,
        CreateInfoSourceError,
    ) as exc:
        return HTMLResponse(
            f'<div id="swap-error" role="alert" aria-live="polite" aria-atomic="true">'
            f'<p class="text-danger">Could not create source: {html_escape(str(exc))}</p>'
            "</div>",
            status_code=422,
        )

    # Deactivate old primary binding if present
    old_binding = (
        await session.execute(
            select(InfoItemSource).where(
                InfoItemSource.info_item_id == item.info_item_id,
                InfoItemSource.deactivated_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if old_binding is not None:
        old_binding.deactivated_at = datetime.now(UTC)
        await session.flush()

    session.add(
        InfoItemSource(
            info_item_id=item.info_item_id,
            info_source_id=new_src.info_source_id,
        )
    )
    await session.commit()

    await sync_on_source_swap(session, watcher, item, new_src)

    return Response(
        status_code=204,
        headers={"HX-Redirect": f"/dashboard/info-items/{item_id}"},
    )


# ---------------------------------------------------------------------------
# POST /{item_id}/swap-primary-by-id
# ---------------------------------------------------------------------------


@router.post("/{item_id}/swap-primary-by-id")
async def swap_primary_by_id(
    item_id: str,
    info_source_id: str = Form(...),
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
    watcher: "WatcherClient | None" = Depends(get_watcher_client),
) -> Response:
    """Swap primary source to an existing InfoSource by ULID.

    Deactivates the current active binding, creates a new one. Best-effort
    Watcher patch follows commit if watcher_item_id is set.
    """
    item = await _resolve_item(item_id, session)

    try:
        source_ulid = ULID.from_str(info_source_id)
    except Exception:
        return HTMLResponse(
            '<div id="swap-by-id-error" role="alert" aria-live="polite" aria-atomic="true">'
            '<p class="text-danger">Invalid InfoSource ID — must be a ULID.</p>'
            "</div>",
            status_code=422,
        )

    new_src = await session.get(InfoSource, source_ulid)
    if new_src is None:
        raise DashboardNotFound("Information Source not found")

    # Deactivate old primary binding if present
    old_binding = (
        await session.execute(
            select(InfoItemSource).where(
                InfoItemSource.info_item_id == item.info_item_id,
                InfoItemSource.deactivated_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if old_binding is not None:
        old_binding.deactivated_at = datetime.now(UTC)
        await session.flush()

    session.add(
        InfoItemSource(
            info_item_id=item.info_item_id,
            info_source_id=new_src.info_source_id,
        )
    )
    await session.commit()

    await sync_on_source_swap(session, watcher, item, new_src)

    return Response(
        status_code=204,
        headers={"HX-Redirect": f"/dashboard/info-items/{item_id}"},
    )


# ---------------------------------------------------------------------------
# Watcher proxy helpers
# ---------------------------------------------------------------------------


def _format_age(dt: datetime | None) -> str:
    """Return a human-readable relative age string, or '' when dt is None."""
    if dt is None:
        return ""
    now = datetime.now(UTC)
    aware = dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)
    seconds = max(0, int((now - aware).total_seconds()))
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        m = seconds // 60
        return f"{m} min ago"
    if seconds < 86400:
        h = seconds // 3600
        return f"{h} hr ago"
    d = seconds // 86400
    return f"{d} day{'s' if d != 1 else ''} ago"


def _format_spec_summary(source_specs: list) -> str:
    """Return a brief spec summary: '<algorithm> · N spec(s)' or '' when empty.

    Handles both plain dicts and generated attrs models (WatchedItemResponseSourceSpecsItem)
    which store all fields in additional_properties rather than direct attributes.
    """
    if not source_specs:
        return ""
    try:
        spec = source_specs[0]
        spec_dict: dict = spec.to_dict() if hasattr(spec, "to_dict") else spec
        algo = spec_dict.get("extraction", {}).get("algorithm", "")
    except (AttributeError, IndexError, TypeError):
        algo = ""
    n = len(source_specs)
    parts = []
    if algo:
        parts.append(algo)
    parts.append(f"{n} spec{'s' if n != 1 else ''}")
    return " · ".join(parts)


_CADENCE_UNIT_LABELS = {"s": "sec", "m": "min", "h": "hr", "d": "day"}


def _format_cadence(schedule_config: object) -> str:
    """Return a short cadence string from a Watcher schedule_config, or ''.

    Watcher stores cadence as ``{"interval": "<N><unit>"}`` where unit is one of
    ``s``/``m``/``h``/``d`` (see watcher ``parse_interval``). Recognised
    registration cadences render with their friendly label (e.g. ``7d`` →
    "Weekly", shared via ``src.dashboard.cadence``); any other valid interval
    falls back to a generic ``~N unit`` form. Returns ``""`` when the config is
    absent or the interval is missing/unparseable.
    """
    if schedule_config is None:
        return ""
    try:
        interval = schedule_config.additional_properties.get("interval")  # type: ignore[attr-defined]
    except AttributeError:
        return ""
    if not interval:
        return ""
    interval = str(interval).strip()
    if interval in CADENCE_LABELS:
        return CADENCE_LABELS[interval]
    match = re.fullmatch(r"(\d+)([smhd])", interval)
    if match is None:
        return ""
    amount = int(match.group(1))
    unit = match.group(2)
    label = _CADENCE_UNIT_LABELS[unit]
    plural = "s" if (unit == "d" and amount != 1) else ""
    return f"~{amount} {label}{plural}"


async def _render_status_partial(
    request: Request,
    *,
    item: InfoItem,
    watcher: "WatcherClient | None",
    pre_fetched: "WatchedItemResponse | None" = None,
) -> HTMLResponse:
    """Render the _watcher_status.html partial for any state."""
    item_id = str(item.info_item_id)

    if watcher is None:
        return _templates.TemplateResponse(
            request,
            "info_items/_watcher_status.html",
            {"item_id": item_id, "state": "not_configured"},
        )

    if not item.watcher_item_id:
        return _templates.TemplateResponse(
            request,
            "info_items/_watcher_status.html",
            {"item_id": item_id, "state": "not_watching"},
        )

    wi = pre_fetched
    if wi is None:
        try:
            wi = await watcher.get_watched_item(item.watcher_item_id)
        except Exception as e:
            return _templates.TemplateResponse(
                request,
                "info_items/_watcher_status.html",
                {"item_id": item_id, "state": "degraded", "error_message": str(e)},
            )

    return _templates.TemplateResponse(
        request,
        "info_items/_watcher_status.html",
        {
            "item_id": item_id,
            "state": "watching",
            "watched_item": wi,
            "last_checked_ago": _format_age(wi.last_checked_at),
            "last_changed_ago": _format_age(wi.last_changed_at),
            "cadence": _format_cadence(wi.default_schedule_config),
        },
    )


async def _render_watcher_section(
    request: Request,
    *,
    item: InfoItem,
    watcher: "WatcherClient | None",
) -> HTMLResponse:
    """Render the _watcher_section.html partial for any state."""
    item_id = str(item.info_item_id)

    if watcher is None:
        return _templates.TemplateResponse(
            request,
            "info_items/_watcher_section.html",
            {"item_id": item_id, "state": "not_configured"},
        )

    if not item.watcher_item_id:
        return _templates.TemplateResponse(
            request,
            "info_items/_watcher_section.html",
            {"item_id": item_id, "state": "not_watching"},
        )

    try:
        wi = await watcher.get_watched_item(item.watcher_item_id)
    except Exception as e:
        return _templates.TemplateResponse(
            request,
            "info_items/_watcher_section.html",
            {"item_id": item_id, "state": "degraded", "error_message": str(e)},
        )

    watcher_display_base = os.environ.get("WATCHER_PUBLIC_BASE_URL", "").strip() or watcher.base_url
    watcher_url = f"{watcher_display_base}/watched-items/{item.watcher_item_id}"
    specs = list(wi.source_specs) if wi.source_specs else []
    return _templates.TemplateResponse(
        request,
        "info_items/_watcher_section.html",
        {
            "item_id": item_id,
            "state": "watching",
            "watched_item": wi,
            "spec_summary": _format_spec_summary(specs),
            "last_checked_ago": _format_age(wi.last_checked_at),
            "last_changed_ago": _format_age(wi.last_changed_at),
            "cadence": _format_cadence(wi.default_schedule_config),
            "watcher_url": watcher_url,
        },
    )


# ---------------------------------------------------------------------------
# GET /{item_id}/watcher-status  (HTMX partial)
# ---------------------------------------------------------------------------


@router.get("/{item_id}/watcher-status", response_class=HTMLResponse)
async def watcher_status(
    item_id: str,
    request: Request,
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
    watcher: "WatcherClient | None" = Depends(get_watcher_client),
) -> HTMLResponse:
    """HTMX partial: load WatchedItem health strip from Watcher."""
    item = await _resolve_item(item_id, session)
    return await _render_status_partial(request, item=item, watcher=watcher)


# ---------------------------------------------------------------------------
# GET /{item_id}/watcher-section  (HTMX partial — Section 3)
# ---------------------------------------------------------------------------


@router.get("/{item_id}/watcher-section", response_class=HTMLResponse)
async def watcher_section(
    item_id: str,
    request: Request,
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
    watcher: "WatcherClient | None" = Depends(get_watcher_client),
) -> HTMLResponse:
    """HTMX partial: detailed Watcher panel for Section 3 of the detail page."""
    item = await _resolve_item(item_id, session)
    return await _render_watcher_section(request, item=item, watcher=watcher)


# ---------------------------------------------------------------------------
# POST /{item_id}/check-now
# ---------------------------------------------------------------------------


@router.post("/{item_id}/check-now", response_class=HTMLResponse)
async def check_now(
    item_id: str,
    request: Request,
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
    watcher: "WatcherClient | None" = Depends(get_watcher_client),
) -> HTMLResponse:
    """Proxy to Watcher check-now; re-renders the watcher-status partial."""
    item = await _resolve_item(item_id, session)

    if watcher is None or not item.watcher_item_id:
        return await _render_status_partial(request, item=item, watcher=watcher)

    wi: WatchedItemResponse | None = None
    try:
        wi = await watcher.check_now(item.watcher_item_id)
    except Exception:
        pass  # wi stays None; _render_status_partial re-fetches — shows degraded if that also fails

    response = await _render_status_partial(request, item=item, watcher=watcher, pre_fetched=wi)
    response.headers["HX-Trigger"] = '{"watcherUpdated":{}}'
    return response


# ---------------------------------------------------------------------------
# POST /{item_id}/begin-watching
# ---------------------------------------------------------------------------


@router.post("/{item_id}/begin-watching", response_class=HTMLResponse)
async def begin_watching(
    item_id: str,
    request: Request,
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
    watcher: "WatcherClient | None" = Depends(get_watcher_client),
) -> HTMLResponse:
    """Provision a WatchedItem on demand for pre-existing InfoItems."""
    item = await _resolve_item(item_id, session)

    if item.watcher_item_id:
        # Already provisioned — just re-render current state.
        return await _render_status_partial(request, item=item, watcher=watcher)

    # Find the active primary source.
    binding = (
        await session.execute(
            select(InfoItemSource).where(
                InfoItemSource.info_item_id == item.info_item_id,
                InfoItemSource.deactivated_at.is_(None),
            )
        )
    ).scalar_one_or_none()

    if binding is None:
        return await _render_status_partial(request, item=item, watcher=watcher)

    primary_src = await session.get(InfoSource, binding.info_source_id)
    if primary_src is None:
        return await _render_status_partial(request, item=item, watcher=watcher)

    await provision_on_create(session, watcher, item, primary_src)

    response = await _render_status_partial(request, item=item, watcher=watcher)
    response.headers["HX-Trigger"] = '{"watcherUpdated":{}}'
    return response


# ---------------------------------------------------------------------------
# POST /{item_id}/resync-watcher
# ---------------------------------------------------------------------------


@router.post("/{item_id}/resync-watcher", response_class=HTMLResponse)
async def resync_watcher(
    item_id: str,
    request: Request,
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
    watcher: "WatcherClient | None" = Depends(get_watcher_client),
) -> HTMLResponse:
    """PATCH WatchedItem with current URL and specs; re-renders status partial."""
    item = await _resolve_item(item_id, session)

    if watcher is None or not item.watcher_item_id:
        return await _render_status_partial(request, item=item, watcher=watcher)

    binding = (
        await session.execute(
            select(InfoItemSource).where(
                InfoItemSource.info_item_id == item.info_item_id,
                InfoItemSource.deactivated_at.is_(None),
            )
        )
    ).scalar_one_or_none()

    if binding is not None:
        primary_src = await session.get(InfoSource, binding.info_source_id)
        if primary_src is not None:
            await sync_on_source_swap(session, watcher, item, primary_src)

    response = await _render_status_partial(request, item=item, watcher=watcher)
    response.headers["HX-Trigger"] = '{"watcherUpdated":{}}'
    return response
