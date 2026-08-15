"""Dashboard — Information Items (list, detail, create, sub-resource mutations)."""

import json
import os
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from html import escape as html_escape
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID
from watcher_client.errors import WatcherConflict, WatcherNotFound, WatcherResponseError

from src.api.deps import get_db_session, get_watcher_client
from src.api.errors import raise_envelope
from src.core.logging import get_logger
from src.core.services.registry_announcement import announce_info_item
from src.core.watch_spec_schema.validator import validate_watch_spec
from src.core.watcher_provisioning import (
    WatcherSyncOutcome,
    provision_on_create,
    sync_on_source_swap,
)

if TYPE_CHECKING:
    from watcher_client import WatcherClient

from src.core.models import (
    InfoItem,
    InfoItemRepSpec,
    InfoItemSource,
    InfoSource,
    RepSpec,
    SourceRevision,
    WatchStatus,
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
from src.dashboard.cadence import CADENCE_LABELS, CADENCE_OPTIONS
from src.dashboard.deps import get_dashboard_user
from src.dashboard.exceptions import DashboardNotFound
from src.dashboard.pagination import Pagination, pagination
from src.dashboard.watch_panel import build_watch_context

router = APIRouter(prefix="/dashboard/info-items")

_templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

logger = get_logger(__name__)


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
    page: Pagination = Depends(pagination),
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """Paginated list with optional name search."""
    stmt = select(InfoItem).order_by(InfoItem.created_at, InfoItem.info_item_id)
    if name_contains:
        stmt = stmt.where(InfoItem.name.ilike(f"%{name_contains}%"))
    stmt = stmt.offset(page.offset).limit(page.limit + 1)

    rows = list((await session.execute(stmt)).scalars().all())
    has_more = len(rows) > page.limit
    rows = rows[: page.limit]

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
            "limit": page.limit,
            "offset": page.offset,
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

    # Same transaction as the create: live if bound, skipped if bare.
    await announce_info_item(session, item.info_item_id)
    await session.commit()

    return RedirectResponse(
        url=f"/dashboard/info-items/{item.info_item_id}",
        status_code=303,
    )


async def _load_active_rep_spec_assignments(
    item_id: ULID, session: AsyncSession
) -> tuple[list[InfoItemRepSpec], dict[ULID, RepSpec]]:
    """Active (non-deactivated) RepSpec assignments for *item_id* + their RepSpecs."""
    irs_rows = list(
        (
            await session.execute(
                select(InfoItemRepSpec).where(
                    InfoItemRepSpec.info_item_id == item_id,
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
    return irs_rows, rep_specs_by_id


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
    spec_summary_by_source_id: dict[ULID, str] = {}
    if source_ids:
        for src in (
            await session.execute(
                select(InfoSource).where(InfoSource.info_source_id.in_(source_ids))
            )
        ).scalars():
            sources_by_id[src.info_source_id] = src
            spec_summary_by_source_id[src.info_source_id] = _format_spec_summary(
                list(src.source_specs) if src.source_specs else []
            )

    # Active rep_spec assignments + RepSpec rows
    irs_rows, rep_specs_by_id = await _load_active_rep_spec_assignments(item.info_item_id, session)

    # Revision history (last 50). Sourced from source_revisions captured across
    # ALL of the item's InfoSource bindings — active primary plus previous
    # primaries (deactivated info_item_sources rows, preserved as succession
    # history) — newest first. The item's content timeline is a query over its
    # bindings, not the info_item_source_revisions pin table (which nothing
    # auto-populates; see archiver#101).
    #
    # One join yields the distinct bound InfoSources; it doubles as the
    # Source/URL lookup (covering deactivated previous primaries, absent from the
    # active-only sources_by_id) and the id set for the revisions query.
    rev_sources_by_id: dict[ULID, InfoSource] = {
        src.info_source_id: src
        for src in (
            await session.execute(
                select(InfoSource)
                .join(InfoItemSource, InfoItemSource.info_source_id == InfoSource.info_source_id)
                .where(InfoItemSource.info_item_id == item.info_item_id)
                .distinct()
            )
        ).scalars()
    }
    revisions: list[SourceRevision] = []
    if rev_sources_by_id:
        revisions = list(
            (
                await session.execute(
                    select(SourceRevision)
                    .where(SourceRevision.info_source_id.in_(list(rev_sources_by_id)))
                    .order_by(
                        SourceRevision.captured_at.desc(),
                        SourceRevision.source_revision_id.desc(),
                    )
                    .limit(50)
                )
            )
            .scalars()
            .all()
        )

    # Browser deeplink to the Watcher item, used to link the "Watcher" section
    # header. Prefers WATCHER_PUBLIC_BASE_URL (browser-facing) over the internal
    # WATCHER_BASE_URL, mirroring _render_watcher_section. None when the item is
    # not yet watched or no Watcher base is configured.
    watcher_base = (
        os.environ.get("WATCHER_PUBLIC_BASE_URL", "").strip()
        or os.environ.get("WATCHER_BASE_URL", "").strip()
    )
    watcher_deeplink = (
        f"{watcher_base}/watched-items/{item.watcher_item_id}"
        if watcher_base and item.watcher_item_id
        else None
    )

    return _templates.TemplateResponse(
        request,
        "info_items/detail.html",
        {
            "user": user,
            "item": item,
            "iis_rows": iis_rows,
            "sources_by_id": sources_by_id,
            "spec_summary_by_source_id": spec_summary_by_source_id,
            "irs_rows": irs_rows,
            "rep_specs_by_id": rep_specs_by_id,
            "revisions": revisions,
            "rev_sources_by_id": rev_sources_by_id,
            "now": datetime.now(UTC),
            "watcher_deeplink": watcher_deeplink,
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

    await announce_info_item(session, item_ulid)
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

    # Revoked: no active primary remains, and silence would leave the consumer
    # fetching the retired URL until the next mutation.
    await announce_info_item(session, item_ulid)
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


@router.delete("/{item_id}/rep-spec-assignments/{aid}", response_class=HTMLResponse)
async def deactivate_rep_spec_assignment(
    item_id: str,
    aid: str,
    request: Request,
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """Deactivate a RepSpec assignment and re-render the assignments section (HTMX).

    The re-rendered `_rep_spec_assignments.html` fragment updates the table +
    empty-state in one swap and moves focus to the section heading.
    """
    try:
        item_ulid = ULID.from_str(item_id)
        aid_ulid = ULID.from_str(aid)
    except Exception as e:
        raise DashboardNotFound("Assignment not found") from e

    assignment = await session.get(InfoItemRepSpec, aid_ulid)
    if assignment is None or assignment.info_item_id != item_ulid:
        raise DashboardNotFound("Assignment not found")

    # Idempotent: don't overwrite the original deactivation timestamp on a repeat call.
    if assignment.deactivated_at is None:
        assignment.deactivated_at = datetime.now(UTC)
        await session.flush()
        await session.commit()

    irs_rows, rep_specs_by_id = await _load_active_rep_spec_assignments(item_ulid, session)
    return _templates.TemplateResponse(
        request,
        "info_items/_rep_spec_assignments.html",
        {
            "user": user,
            "item_id": item_ulid,
            "irs_rows": irs_rows,
            "rep_specs_by_id": rep_specs_by_id,
            "swapped": True,
        },
    )


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
    # ONE announcement for the whole swap, carrying the final state — announcing
    # the deactivate and the bind separately would be revoked-then-live, and the
    # consumer would destroy and recreate its row, losing every local column.
    await announce_info_item(session, item.info_item_id)
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
    # ONE announcement for the whole swap, carrying the final state — announcing
    # the deactivate and the bind separately would be revoked-then-live, and the
    # consumer would destroy and recreate its row, losing every local column.
    await announce_info_item(session, item.info_item_id)
    await session.commit()

    await sync_on_source_swap(session, watcher, item, new_src)

    return Response(
        status_code=204,
        headers={"HX-Redirect": f"/dashboard/info-items/{item_id}"},
    )


# ---------------------------------------------------------------------------
# Watcher proxy helpers
# ---------------------------------------------------------------------------


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


# Copy for the WatchedItem-deleted (404) reconcile paths — shared so the flash
# and degraded-panel wording stay aligned across the render and action handlers.
_WATCHER_REMOVED_FLASH = "This item is no longer watched — it was removed in Watcher."
_RECONCILE_FAILED_FLASH = (
    "Watcher reports this item gone, but the local record couldn't be updated — retrying shortly."
)
_RECONCILE_FAILED_MSG = "couldn't update the local record after Watcher reported it gone"
_POLICY_WRITE_FAILED_MSG = "couldn't save the watch policy"
_POLICY_WRITE_FAILED_FLASH = "Couldn't update the watch state — the change was not saved."
# Suffix for the honest "contract drift" flash: a WatcherResponseError means the
# watcher_client SDK is stale relative to the live Watcher API, not that Watcher is
# down. Deliberately omits "try again" — retrying a contract mismatch never helps.
_WATCHER_CONTRACT_SUFFIX = (
    "Watcher returned an unexpected response; the integration may be out of date. "
    "Check the logs — retrying won't help."
)


def _status_degraded(request: Request, item_id: str, error_message: str) -> HTMLResponse:
    """Render the _watcher_status.html partial in the degraded state from an id alone.

    Takes ``item_id`` (not an ``InfoItem``) so it is safe to call after a failed
    reconcile, when the ORM object may have expired attributes.
    """
    return _templates.TemplateResponse(
        request,
        "info_items/_watcher_status.html",
        {"item_id": item_id, "state": "degraded", "error_message": error_message},
    )


def _section_degraded(request: Request, item_id: str, error_message: str) -> HTMLResponse:
    """Render the _watcher_section.html partial in the degraded state from an id alone."""
    return _templates.TemplateResponse(
        request,
        "info_items/_watcher_section.html",
        {"item_id": item_id, "state": "degraded", "error_message": error_message},
    )


async def _clear_stale_watcher_link(session: AsyncSession, item: InfoItem) -> bool:
    """Best-effort NULL of a watcher_item_id after Watcher reports the WatchedItem
    gone (404). Returns ``True`` when the link was durably cleared, ``False`` when
    the commit failed.

    A permanently deleted WatchedItem 404s on every read. Without this the
    InfoItem sticks in the ``degraded`` state forever — indistinguishable from a
    transient Watcher outage — and "Begin Watching" never reappears (it is gated
    on a NULL ``watcher_item_id``). Clearing the pointer lets the item fall back
    to ``not_watching`` so an operator can re-provision. Only a confirmed 404
    clears the link; transient failures keep it so a brief outage never drops it.

    The cached ``watch_status`` row goes with it, in the same transaction
    (archiver#151 CR round 1, finding 3). It describes a WatchedItem that no
    longer exists, and leaving it behind does two kinds of harm: the panel keeps
    rendering ``watching`` instead of offering "Begin Watching", and if the item
    is later re-provisioned under a *new* id, the dead WatchedItem's health is
    reported as the new one's. The panel guards against the first independently
    — the invariant should not depend on this cleanup having run — but the stale
    data itself is only fixable here.

    Never raises: the render/action paths it serves are designed to degrade rather
    than 500, so a failed commit is rolled back, logged, and reported as ``False``
    (the caller keeps degrading). ``item`` is refreshed on failure so callers may
    keep using it; the next read retries the clear.
    """
    item_id = str(item.info_item_id)  # capture before commit/rollback can expire it
    stale_id = item.watcher_item_id
    item.watcher_item_id = None
    try:
        await session.execute(
            delete(WatchStatus).where(WatchStatus.info_item_id == item.info_item_id)
        )
        await session.commit()
    except Exception:
        logger.exception(
            "Failed to clear stale watcher_item_id %s for InfoItem %s (WatchedItem 404)",
            stale_id,
            item_id,
        )
        try:
            await session.rollback()
            await session.refresh(item)
        except Exception:
            logger.exception(
                "Recovery after failed watcher_item_id clear also failed for InfoItem %s",
                item_id,
            )
        return False
    logger.info(
        "Cleared stale watcher_item_id %s for InfoItem %s (WatchedItem 404)",
        stale_id,
        item_id,
    )
    return True


async def _watch_template_context(
    session: AsyncSession, item: InfoItem, watcher: "WatcherClient | None"
) -> dict:
    """Panel context from local state alone — zero SDK calls (archiver#151).

    ``watch_status`` (the ``info.watch-status`` cache), the item's own
    ``watch_spec`` / generations, and the latest revision of the active source
    are everything the render needs. The Watcher client gates only the action
    buttons, which still ride the SDK until the control-plane cutover
    (archiver#158).
    """
    status = await session.get(WatchStatus, item.info_item_id)
    last_changed_at = (
        await session.execute(
            select(func.max(SourceRevision.captured_at))
            .join(
                InfoItemSource,
                InfoItemSource.info_source_id == SourceRevision.info_source_id,
            )
            .where(
                InfoItemSource.info_item_id == item.info_item_id,
                InfoItemSource.deactivated_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    watch = build_watch_context(
        item=item, status=status, last_changed_at=last_changed_at, now=datetime.now(UTC)
    )
    return {
        "item_id": str(item.info_item_id),
        "state": watch["state"],
        "watch": watch,
        "can_act": watcher is not None and bool(item.watcher_item_id),
        "can_provision": watcher is not None,
        # Cadence is Archiver's own policy as of archiver#158, so its editor is
        # deliberately NOT gated on ``can_act``: a WatchedItem need not exist for
        # the registry to hold an opinion, and the announcement is what carries
        # it. ``cadence_value`` is the announced interval, "" meaning delegate.
        "cadence_options": CADENCE_LABELS,
        "cadence_value": (item.watch_spec or {}).get("interval") or "",
    }


async def _render_status_partial(
    request: Request,
    *,
    session: AsyncSession,
    item: InfoItem,
    watcher: "WatcherClient | None",
) -> HTMLResponse:
    """Render the _watcher_status.html partial from local state."""
    context = await _watch_template_context(session, item, watcher)
    return _templates.TemplateResponse(request, "info_items/_watcher_status.html", context)


async def _render_watcher_section(
    request: Request,
    *,
    session: AsyncSession,
    item: InfoItem,
    watcher: "WatcherClient | None",
) -> HTMLResponse:
    """Render the _watcher_section.html partial from local state."""
    context = await _watch_template_context(session, item, watcher)
    return _templates.TemplateResponse(request, "info_items/_watcher_section.html", context)


def _watcher_hx_trigger(flash: tuple[str, str] | None = None) -> str:
    """Build the ``HX-Trigger`` header value for Watcher action endpoints.

    Always fires ``watcherUpdated`` so Section 3 self-refreshes. When ``flash``
    (a ``(level, body)`` pair) is supplied, also fires ``showFlash`` so
    ``flash.js`` surfaces the message to the operator instead of failing silently.
    """
    triggers: dict[str, object] = {"watcherUpdated": {}}
    if flash is not None:
        triggers["showFlash"] = {"level": flash[0], "body": flash[1]}
    return json.dumps(triggers)


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
    return await _render_status_partial(request, session=session, item=item, watcher=watcher)


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
    return await _render_watcher_section(request, session=session, item=item, watcher=watcher)


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
        return await _render_status_partial(request, session=session, item=item, watcher=watcher)

    flash: tuple[str, str] | None = None
    reconcile_failed = False
    try:
        await watcher.check_now(item.watcher_item_id)
    except WatcherNotFound:
        # The WatchedItem is gone (deleted in Watcher). Clear the stale link so
        # the partial falls back to not_watching instead of looping on 404.
        if await _clear_stale_watcher_link(session, item):
            flash = ("error", _WATCHER_REMOVED_FLASH)
        else:
            flash = ("error", _RECONCILE_FAILED_FLASH)
            reconcile_failed = True
    except WatcherConflict:
        # Watcher 409s on check-now of a paused item. The button is hidden when
        # paused, but guard direct posts with the accurate reason.
        flash = ("error", "Can't check a paused item — resume it first.")
    except WatcherResponseError:
        # Response couldn't be parsed — the watcher_client SDK is stale, not a
        # transport outage. Flash honestly so the operator doesn't keep retrying.
        flash = ("error", f"Couldn't trigger a check — {_WATCHER_CONTRACT_SUFFIX}")
    except Exception:
        # The render below is local-state and cannot fail on Watcher being
        # down; surface the action failure as a flash.
        flash = ("error", "Couldn't trigger a check — Watcher is unavailable. Try again shortly.")

    if reconcile_failed:
        # Clearing the link failed to commit; render degraded straight from the path
        # id — don't re-render through the item (attrs may be expired) or re-fetch.
        response = _status_degraded(request, item_id, _RECONCILE_FAILED_MSG)
    else:
        response = await _render_status_partial(
            request, session=session, item=item, watcher=watcher
        )
    response.headers["HX-Trigger"] = _watcher_hx_trigger(flash)
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
        return await _render_status_partial(request, session=session, item=item, watcher=watcher)

    # Find the active primary source.
    binding = (
        await session.execute(
            select(InfoItemSource).where(
                InfoItemSource.info_item_id == item.info_item_id,
                InfoItemSource.deactivated_at.is_(None),
            )
        )
    ).scalar_one_or_none()

    primary_src = (
        await session.get(InfoSource, binding.info_source_id) if binding is not None else None
    )
    if primary_src is None:
        # No active primary source to watch — flash rather than silently re-render
        # (but stay quiet when Watcher is unconfigured: the partial already shows
        # the not_configured state, and a missing-source flash would mislead).
        response = await _render_status_partial(
            request, session=session, item=item, watcher=watcher
        )
        flash: tuple[str, str] | None = (
            ("error", "No primary source to watch — bind one first.")
            if watcher is not None
            else None
        )
        response.headers["HX-Trigger"] = _watcher_hx_trigger(flash)
        return response

    outcome = await provision_on_create(session, watcher, item, primary_src)
    flash: tuple[str, str] | None = None
    if outcome is WatcherSyncOutcome.FAILED:
        flash = ("error", "Couldn't start watching — Watcher is unavailable. Try again shortly.")
    elif outcome is WatcherSyncOutcome.CONTRACT_ERROR:
        flash = ("error", f"Couldn't start watching — {_WATCHER_CONTRACT_SUFFIX}")

    response = await _render_status_partial(request, session=session, item=item, watcher=watcher)
    response.headers["HX-Trigger"] = _watcher_hx_trigger(flash)
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
        return await _render_status_partial(request, session=session, item=item, watcher=watcher)

    binding = (
        await session.execute(
            select(InfoItemSource).where(
                InfoItemSource.info_item_id == item.info_item_id,
                InfoItemSource.deactivated_at.is_(None),
            )
        )
    ).scalar_one_or_none()

    primary_src = (
        await session.get(InfoSource, binding.info_source_id) if binding is not None else None
    )

    flash: tuple[str, str] | None = None
    if primary_src is None:
        # Watched item with no active primary source — nothing to re-sync.
        flash = ("error", "No primary source to re-sync — bind one first.")
    else:
        outcome = await sync_on_source_swap(session, watcher, item, primary_src)
        if outcome is WatcherSyncOutcome.FAILED:
            flash = (
                "error",
                "Couldn't re-sync with Watcher — it's unavailable. Try again shortly.",
            )
        elif outcome is WatcherSyncOutcome.CONTRACT_ERROR:
            flash = ("error", f"Couldn't re-sync with Watcher — {_WATCHER_CONTRACT_SUFFIX}")
        elif outcome is WatcherSyncOutcome.NOT_FOUND:
            # The WatchedItem is gone. Since #151 the render never observes a
            # 404 (it is local-state), so the action outcome carries the
            # reconcile: clear the stale link and fall back to not_watching.
            if await _clear_stale_watcher_link(session, item):
                flash = ("error", _WATCHER_REMOVED_FLASH)
            else:
                response = _status_degraded(request, item_id, _RECONCILE_FAILED_MSG)
                response.headers["HX-Trigger"] = _watcher_hx_trigger(
                    ("error", _RECONCILE_FAILED_FLASH)
                )
                return response

    response = await _render_status_partial(request, session=session, item=item, watcher=watcher)
    response.headers["HX-Trigger"] = _watcher_hx_trigger(flash)
    return response


# ---------------------------------------------------------------------------
# POST /{item_id}/toggle-watch-active  (pause / resume)
# ---------------------------------------------------------------------------


@router.post("/{item_id}/toggle-watch-active", response_class=HTMLResponse)
async def toggle_watch_active(
    item_id: str,
    request: Request,
    active: str = Form(default=""),
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
    watcher: "WatcherClient | None" = Depends(get_watcher_client),
) -> HTMLResponse:
    """Pause or resume by writing ``watch_active`` locally and announcing it.

    ``active`` is the desired target state ("true" → resume, anything else →
    pause); the button submits the opposite of the current *applied* state.

    **The control plane is local as of archiver#158.** This was a
    ``patch_watched_item`` over the SDK; it is now an ``UPDATE`` plus an
    announcement in one transaction, and Watcher reconciles it off
    ``info.registry``. The re-render still shows *applied* state (archiver#151),
    so the button reflects the change only once Watcher reports it back on
    ``info.watch-status`` — the lag window is the announcement round-trip and
    stays visible as generation drift rather than becoming invisible.

    **The archived-item guard is deliberately gone.** Watcher used to reject
    pause/resume on an archived WatchedItem with a 409, which this caught and
    flashed. Archiver has no local notion of archived — only ``domains``
    carries one — and the design settled that a Watcher-local pause is
    *reverted* by reconciliation, with the break-glass being host-level
    ``domain_suspended``, untouched because it is mechanism rather than policy.
    Archive is the same shape: Watcher-local mechanism. It now surfaces as
    ``applied_active != active`` on the return leg, which the panel already
    renders — visible divergence instead of a silent rejection.
    """
    item = await _resolve_item(item_id, session)

    try:
        item.watch_active = active == "true"
        await announce_info_item(session, item.info_item_id)
        await session.commit()
    except Exception:
        # A failed local write is our fault, not an upstream outage — but the
        # panel degrades rather than 500s (the #151 precedent). Render from the
        # path id, not through ``item``: the rollback expires its attributes and
        # re-reading them would emit IO from the template and raise
        # MissingGreenlet.
        await session.rollback()
        logger.exception("Local watch_active write failed for InfoItem %s", item_id)
        response = _status_degraded(request, item_id, _POLICY_WRITE_FAILED_MSG)
        response.headers["HX-Trigger"] = _watcher_hx_trigger(("error", _POLICY_WRITE_FAILED_FLASH))
        return response

    response = await _render_status_partial(request, session=session, item=item, watcher=watcher)
    response.headers["HX-Trigger"] = _watcher_hx_trigger()
    return response


# ---------------------------------------------------------------------------
# POST /{item_id}/watch-cadence  (set the announced fetch cadence)
# ---------------------------------------------------------------------------


@router.post("/{item_id}/watch-cadence", response_class=HTMLResponse)
async def set_watch_cadence(
    item_id: str,
    request: Request,
    interval: str = Form(default=""),
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
    watcher: "WatcherClient | None" = Depends(get_watcher_client),
) -> HTMLResponse:
    """Replace the item's cadence policy and announce it (archiver#158).

    **This affordance did not exist before the cutover.** Cadence was chosen at
    registration and then display-only, because the live value was Watcher's and
    the dashboard had nothing local to edit.

    The empty selection means *delegate* — the document keeps only
    ``schema_version`` and the consumer applies its own default, which may be a
    per-domain one rather than a global constant. That is why this replaces the
    whole document instead of merging: a merge would make "delegate"
    unreachable once an interval had ever been set, the same reasoning the API's
    whole-document ``PUT /watch-spec`` gives.

    ``interval`` is validated against the dashboard's offered vocabulary, not
    just the schema. The schema admits any ``^[0-9]+[smhd]$``; the dropdown is a
    deliberately narrower UI subset, and a hand-posted value outside it is a
    mistake worth refusing rather than a power-user feature — the API route is
    the escape hatch for the full grammar.
    """
    item = await _resolve_item(item_id, session)

    if interval and interval not in CADENCE_OPTIONS:
        response = await _render_watcher_section(
            request, session=session, item=item, watcher=watcher
        )
        response.headers["HX-Trigger"] = _watcher_hx_trigger(
            ("error", f"“{interval}” is not one of the offered cadences.")
        )
        return response

    document = {"schema_version": 1}
    if interval:
        document["interval"] = interval

    ok, errors = validate_watch_spec(document)
    if not ok:
        # Belt and braces: the vocabulary check above should make this
        # unreachable. If the two ever disagree, refuse rather than announce a
        # document the consumer will fail to parse.
        logger.error("Dashboard built an invalid watch_spec for InfoItem %s: %s", item_id, errors)
        response = await _render_watcher_section(
            request, session=session, item=item, watcher=watcher
        )
        response.headers["HX-Trigger"] = _watcher_hx_trigger(
            ("error", "Couldn't set the cadence — the policy document was rejected.")
        )
        return response

    try:
        item.watch_spec = document
        await announce_info_item(session, item.info_item_id)
        await session.commit()
    except Exception:
        await session.rollback()
        logger.exception("Local watch_spec write failed for InfoItem %s", item_id)
        response = _section_degraded(request, item_id, _POLICY_WRITE_FAILED_MSG)
        response.headers["HX-Trigger"] = _watcher_hx_trigger(("error", _POLICY_WRITE_FAILED_FLASH))
        return response

    response = await _render_watcher_section(request, session=session, item=item, watcher=watcher)
    response.headers["HX-Trigger"] = _watcher_hx_trigger()
    return response
