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
    ReplicationCommand,
    RepSpec,
)
from src.core.services.replication_issuance import ManualIssuanceError, issue_for_assignment
from src.core.services.replication_status import latest_commands_by_assignment
from src.core.tools.create_rep_spec import InvalidRepSpecError, create_rep_spec
from src.core.tools.update_rep_spec import (
    InvalidRepSpecError as UpdateInvalidRepSpecError,
)
from src.core.tools.update_rep_spec import (
    RepSpecNotDraftError,
    assignment_count,
    update_rep_spec,
)
from src.dashboard.deps import get_dashboard_user
from src.dashboard.exceptions import DashboardNotFound
from src.dashboard.pagination import Pagination, pagination
from src.dashboard.replication_actions import outcome_flash_header

router = APIRouter(prefix="/dashboard/rep-specs")

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
) -> tuple[list[InfoItemRepSpec], dict[ULID, InfoItem], dict[ULID, ReplicationCommand]]:
    """Active assignments for *spec*, their InfoItems, and their latest occasion.

    The same question the InfoItem hub answers (archiver#171), asked from the
    other side: "which items does this spec replicate?" is only half an answer
    without "and which of them actually did?".
    """
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
    latest_commands = await latest_commands_by_assignment(session, [a.id for a in assignment_rows])
    return assignment_rows, items_by_id, latest_commands


async def _document_card_context(
    spec: RepSpec,
    session: AsyncSession,
    *,
    doc_error: str | None = None,
    doc_input: str | None = None,
    swapped: bool = False,
) -> dict:
    """Context for ``rep_specs/_document_card.html``.

    ``is_draft`` gates the editor. It counts *all* assignment rows, not just
    active ones — ``_load_active_assignments`` filters to ``deactivated_at IS
    NULL`` and is deliberately not reused here, since a deactivated assignment
    still means a replication run happened under this document (archiver#83).
    """
    count = await assignment_count(session, spec.rep_spec_id)
    return {
        "spec": spec,
        "doc_json": json.dumps(spec.document, indent=2),
        "doc_input": doc_input,
        "doc_error": doc_error,
        "assignment_count": count,
        "is_draft": count == 0,
        "swapped": swapped,
    }


# ---------------------------------------------------------------------------
# GET /dashboard/rep-specs/
# ---------------------------------------------------------------------------


@router.get("/", response_class=HTMLResponse)
async def list_rep_specs(
    request: Request,
    provider: str | None = None,
    page: Pagination = Depends(pagination),
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """Paginated list with optional provider filter."""
    stmt = select(RepSpec).order_by(RepSpec.created_at, RepSpec.rep_spec_id)
    if provider:
        stmt = stmt.where(RepSpec.provider == provider)
    stmt = stmt.offset(page.offset).limit(page.limit + 1)

    rows = list((await session.execute(stmt)).scalars().all())
    has_more = len(rows) > page.limit
    rows = rows[: page.limit]

    return _templates.TemplateResponse(
        request,
        "rep_specs/list.html",
        {
            "user": user,
            "specs": rows,
            "has_more": has_more,
            "limit": page.limit,
            "offset": page.offset,
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
    """Detail: provider, name, document (editable while draft), active assignments."""
    spec = await _resolve_spec(spec_id, session)
    assignment_rows, items_by_id, latest_commands = await _load_active_assignments(spec, session)

    return _templates.TemplateResponse(
        request,
        "rep_specs/detail.html",
        {
            "user": user,
            "spec": spec,
            "assignments": assignment_rows,
            "items_by_id": items_by_id,
            "latest_commands": latest_commands,
            **await _document_card_context(spec, session),
        },
    )


# ---------------------------------------------------------------------------
# DELETE /dashboard/rep-specs/{id}/assignments/{aid}
# ---------------------------------------------------------------------------


@router.post("/{spec_id}/document")
async def update_rep_spec_document_view(
    spec_id: str,
    request: Request,
    document: str = Form(default=""),
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Replace the document on a draft RepSpec.

    HTMX requests get the re-rendered ``_document_card.html`` partial swapped in
    place: success carries an ``HX-Trigger: showFlash`` toast; any rejection
    swaps the card back with an inline error (status 200 so htmx performs the
    swap) that is announced (``role="alert"``), moves focus to the heading, and
    preserves the operator's submitted text. Non-HTMX requests keep the plain
    full-page POST→303 (success) / 422 re-render (error) fallback. See
    docs/UI.md Detail Screen Conventions.

    A spec that has acquired an assignment since the page was rendered is
    rejected here as well as in the template gate — the editor can be stale.
    """
    spec = await _resolve_spec(spec_id, session)
    is_htmx = bool(request.headers.get("HX-Request"))

    async def _rerender(error: str) -> HTMLResponse:
        # `swapped` is shared across _document_card.html and _assignments.html
        # (both gate a focus script on it), so it must stay False on the
        # full-page path — otherwise the 422 render emits both scripts and the
        # assignments one steals focus away from the error. Matches
        # update_info_source_specs_view, whose non-HTMX path never sets it.
        ctx = await _document_card_context(
            spec, session, doc_error=error, doc_input=document, swapped=is_htmx
        )
        if is_htmx:
            # 200 so htmx swaps the card; the inline error stays visible.
            return _templates.TemplateResponse(request, "rep_specs/_document_card.html", ctx)
        assignment_rows, items_by_id, latest_commands = await _load_active_assignments(
            spec, session
        )
        return _templates.TemplateResponse(
            request,
            "rep_specs/detail.html",
            {
                "user": user,
                "assignments": assignment_rows,
                "items_by_id": items_by_id,
                "latest_commands": latest_commands,
                **ctx,
            },
            status_code=422,
        )

    try:
        doc = json.loads(document) if document.strip() else None
        if not isinstance(doc, dict):
            raise ValueError("not an object")
    except (json.JSONDecodeError, ValueError):
        return await _rerender("document must be a JSON object")

    try:
        await update_rep_spec(session, rep_spec_id=spec.rep_spec_id, document=doc)
    except RepSpecNotDraftError as e:
        return await _rerender(str(e))
    except UpdateInvalidRepSpecError as e:
        return await _rerender(
            "; ".join(err.get("message", "") for err in e.errors) if e.errors else str(e)
        )

    await session.commit()

    if is_htmx:
        await session.refresh(spec)
        response = _templates.TemplateResponse(
            request,
            "rep_specs/_document_card.html",
            await _document_card_context(spec, session, swapped=True),
        )
        response.headers["HX-Trigger"] = json.dumps(
            {"showFlash": {"level": "success", "body": "Document updated."}}
        )
        return response

    return RedirectResponse(url=f"/dashboard/rep-specs/{spec_id}", status_code=303)


# ---------------------------------------------------------------------------
# POST /dashboard/rep-specs/{id}/assignments/{aid}/replicate  (archiver#171)
# ---------------------------------------------------------------------------


@router.post("/{spec_id}/assignments/{aid}/replicate", response_class=HTMLResponse)
async def replicate_assignment_now(
    spec_id: str,
    aid: str,
    request: Request,
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """Issue one replication occasion for this assignment; re-renders the section.

    The InfoItem hub's twin (archiver#171 CR #32). This screen is the natural
    entry point for "this spec's assignments are all stale", and rendering the
    state here while forcing a navigation hop per item to act on it makes the
    diagnosis useless.

    Re-renders the whole section rather than one row, matching the DELETE beside
    it: the row shape here is this table's, not the hub's, and the swap destroys
    the button that was clicked so it has to move focus (CR #37).

    **Every outcome is a 200, and every outcome flashes** — identical handling to
    the hub route, which is why the translation is shared rather than copied
    (CR #36/#42).
    """
    spec = await _resolve_spec(spec_id, session)
    try:
        aid_ulid = ULID.from_str(aid)
    except Exception as e:
        raise DashboardNotFound("Assignment not found") from e

    assignment = await session.get(InfoItemRepSpec, aid_ulid)
    if assignment is None or assignment.rep_spec_id != spec.rep_spec_id:
        raise DashboardNotFound("Assignment not found")

    refusal: ManualIssuanceError | None = None
    issued: ReplicationCommand | None = None
    try:
        issued = await issue_for_assignment(session, assignment)
    except ManualIssuanceError as e:
        # No rollback: every refusal path raises before writing anything.
        refusal = e
    else:
        await session.commit()

    assignment_rows, items_by_id, latest_commands = await _load_active_assignments(spec, session)
    response = _templates.TemplateResponse(
        request,
        "rep_specs/_assignments.html",
        {
            "user": user,
            "spec": spec,
            "assignments": assignment_rows,
            "items_by_id": items_by_id,
            "latest_commands": latest_commands,
            "swapped": True,
        },
    )
    response.headers["HX-Trigger"] = outcome_flash_header(
        refusal=refusal, issued=issued, latest=latest_commands.get(assignment.id)
    )
    return response


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

    # Idempotent: don't overwrite the original deactivation timestamp on a repeat call.
    if assignment.deactivated_at is None:
        assignment.deactivated_at = datetime.now(UTC)
        await session.flush()
        await session.commit()

    assignment_rows, items_by_id, latest_commands = await _load_active_assignments(spec, session)
    return _templates.TemplateResponse(
        request,
        "rep_specs/_assignments.html",
        {
            "user": user,
            "spec": spec,
            "assignments": assignment_rows,
            "items_by_id": items_by_id,
            "latest_commands": latest_commands,
            "swapped": True,
        },
    )
