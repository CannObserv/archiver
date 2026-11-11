"""Dashboard — Information Sources (list, detail, create, edit specs)."""

import json
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.api.deps import get_db_session
from src.core import capture_reader
from src.core.capture_reader import IMAGE_MEDIA_TYPE, CaptureUnavailable, image_uri, read_capture
from src.core.logging import get_logger
from src.core.models import (
    CaptureCommand,
    InfoItem,
    InfoItemSource,
    InfoSource,
    SourceRevision,
)
from src.core.services.capture import (
    DEFAULT_REAP_HORIZON,
    CaptureAlreadyOpen,
    CaptureDisabled,
    CapturePolicyInvalid,
    capture_enabled,
    latest_capture,
    request_capture,
    set_capture_policy,
)
from src.core.services.registry_announcement import announce_for_info_source
from src.core.tools.audit_stored_documents import info_source_findings
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
from src.dashboard.capture_view import POLL_SECONDS as CAPTURE_POLL_SECONDS
from src.dashboard.capture_view import (
    PolicyForm,
    PolicyFormError,
    capture_view,
    parse_policy_form,
    policy_form,
    policy_view,
)
from src.dashboard.deps import get_dashboard_user
from src.dashboard.exceptions import DashboardNotFound
from src.dashboard.pagination import Pagination, pagination
from src.dashboard.stored_documents import finding_views

logger = get_logger(__name__)

router = APIRouter(prefix="/dashboard/info-sources")

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
                .order_by(
                    SourceRevision.captured_at.desc(), SourceRevision.source_revision_id.desc()
                )
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
        "stored_findings": finding_views(info_source_findings(src)),
    }


async def _capture_context(src: InfoSource, session: AsyncSession) -> dict:
    """Everything ``info_sources/_capture_card.html`` reads but ``swapped`` (#380).

    The card's one builder: the detail page, its poll and the button's POST
    all spread it, so no render site can omit ``capture`` and leave the card
    unable to poll.
    """
    enabled = capture_enabled()
    command = await latest_capture(session, src.info_source_id) if enabled else None
    return {
        "src": src,
        "capture_enabled": enabled,
        "capture": capture_view(
            command,
            now=datetime.now(UTC),
            horizon=DEFAULT_REAP_HORIZON,
            image_reader=capture_reader.bound() is not None,
        ),
        "capture_poll_seconds": CAPTURE_POLL_SECONDS,
    }


async def _capture_policy_context(
    src: InfoSource,
    session: AsyncSession,
    *,
    policy_error: str | None = None,
    policy_input: PolicyForm | None = None,
) -> dict:
    """Everything ``info_sources/_capture_policy_card.html`` reads but ``swapped`` (#380 C).

    The card's one builder, spread by the detail page, the specs editor's 422
    fallback and the policy POST. ``policy_input`` echoes a refused submission
    so the operator's edit survives; otherwise the form shows the stored policy.
    ``session`` is unused: every registered builder takes one (test_partial_contracts).
    """
    return {
        "src": src,
        "capture_enabled": capture_enabled(),
        "policy": policy_view(src.capture_policy),
        "policy_form": policy_input or policy_form(src.capture_policy),
        "policy_error": policy_error,
    }


# ---------------------------------------------------------------------------
# GET /dashboard/info-sources/
# ---------------------------------------------------------------------------


@router.get("/", response_class=HTMLResponse)
async def list_info_sources(
    request: Request,
    url_contains: str | None = None,
    page: Pagination = Depends(pagination),
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """Paginated list with optional URL filter."""
    stmt = select(InfoSource).order_by(InfoSource.created_at, InfoSource.info_source_id)
    if url_contains:
        stmt = stmt.where(InfoSource.url.ilike(f"%{url_contains}%"))
    stmt = stmt.offset(page.offset).limit(page.limit + 1)

    rows = list((await session.execute(stmt)).scalars().all())
    has_more = len(rows) > page.limit
    rows = rows[: page.limit]

    return _templates.TemplateResponse(
        request,
        "info_sources/list.html",
        {
            "user": user,
            "sources": rows,
            "has_more": has_more,
            "limit": page.limit,
            "offset": page.offset,
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
    ctx = {
        **await _detail_context(src, user, session),
        **await _capture_context(src, session),
        **await _capture_policy_context(src, session),
    }
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
    preserving submitted text) fallback (progressive enhancement). See
    docs/SCREENS.md.
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
        ctx = {
            **await _detail_context(
                src, user, session, specs_error=error, specs_input=source_specs
            ),
            **await _capture_context(src, session),
            **await _capture_policy_context(src, session),
        }
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

    # Fan out to every item this source actively backs (grain is the item).
    await announce_for_info_source(session, src.info_source_id)
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


# ---------------------------------------------------------------------------
# GET /{source_id}/capture, POST /{source_id}/capture-now  (archiver#380)
# ---------------------------------------------------------------------------

_CAPTURE_OPEN_FLASH = "A capture is already pending for this source - wait for its answer."
_CAPTURE_POLICY_INVALID_FLASH = (
    "This source's capture policy no longer validates - save it again, then capture."
)
_CAPTURE_WRITE_FAILED_FLASH = "Couldn't request the capture - nothing was sent."


def _require_capture() -> None:
    """404 while the switch is off: the routes do not exist until then."""
    if not capture_enabled():
        raise DashboardNotFound("Not found")


@router.get("/{source_id}/capture", response_class=HTMLResponse)
async def capture_card(
    source_id: str,
    request: Request,
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """HTMX partial: the Viewport Capture card, re-read by its own poll while pending."""
    _require_capture()
    src = await _resolve_source(source_id, session)
    context = await _capture_context(src, session)
    return _templates.TemplateResponse(request, "info_sources/_capture_card.html", context)


@router.post("/{source_id}/capture-now", response_model=None)
async def capture_now(
    source_id: str,
    request: Request,
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse | RedirectResponse:
    """Ask Replicator to capture the source now: one ``content.capture`` command, outboxed.

    HTMX: the card swaps in place (pending, polling); a click while one is
    pending writes nothing and flashes. Without JS: a POST → 303 to detail.
    """
    _require_capture()
    src = await _resolve_source(source_id, session)
    flash: dict | None = None
    try:
        await request_capture(session, src.info_source_id, requested_by=user.id)
        await session.commit()
    except CaptureAlreadyOpen:
        await session.rollback()
        flash = {"level": "warning", "body": _CAPTURE_OPEN_FLASH}
    except CapturePolicyInvalid:
        await session.rollback()
        flash = {"level": "error", "body": _CAPTURE_POLICY_INVALID_FLASH}
    except CaptureDisabled as e:
        # The switch flipped between the gate and the write.
        await session.rollback()
        raise DashboardNotFound("Not found") from e
    except Exception:
        await session.rollback()
        logger.exception("Capture request failed for InfoSource %s", source_id)
        flash = {"level": "error", "body": _CAPTURE_WRITE_FAILED_FLASH}

    if not request.headers.get("HX-Request"):
        return RedirectResponse(url=f"/dashboard/info-sources/{source_id}", status_code=303)
    # Re-read after a commit or rollback, which expire the row.
    src = await _resolve_source(source_id, session)
    context = {**await _capture_context(src, session), "swapped": True}
    response = _templates.TemplateResponse(request, "info_sources/_capture_card.html", context)
    if flash is not None:
        response.headers["HX-Trigger"] = json.dumps({"showFlash": flash})
    return response


# ---------------------------------------------------------------------------
# POST /{source_id}/capture-policy  (archiver#380 slice C)
# ---------------------------------------------------------------------------


@router.post("/{source_id}/capture-policy", response_model=None)
async def save_capture_policy(
    source_id: str,
    request: Request,
    action: str = Form(default="save"),
    width: str = Form(default=""),
    height: str = Form(default=""),
    full_page: str | None = Form(default=None),
    wait_kind: str = Form(default=""),
    wait_selector: str = Form(default=""),
    wait_seconds: str = Form(default=""),
    on_revision: str | None = Form(default=None),
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse | RedirectResponse:
    """Save or clear the source's capture policy; the next capture sends it.

    An editor card (docs/SCREENS.md): HTMX swaps ``#capture-policy-card`` in
    place, a refusal at 200 with the error and the input echoed; without JS a
    303 on success and a full-page 422 on a refusal. Sends no command.
    """
    _require_capture()
    src = await _resolve_source(source_id, session)
    is_htmx = bool(request.headers.get("HX-Request"))
    submitted = PolicyForm(
        width=width,
        height=height,
        full_page=full_page is not None,
        wait_kind=wait_kind,
        wait_selector=wait_selector,
        wait_seconds=wait_seconds,
        on_revision=on_revision is not None,
    )
    try:
        policy = None if action == "clear" else parse_policy_form(submitted)
    except PolicyFormError as e:
        context = await _capture_policy_context(
            src, session, policy_error=str(e), policy_input=submitted
        )
        if is_htmx:
            return _templates.TemplateResponse(
                request, "info_sources/_capture_policy_card.html", {**context, "swapped": True}
            )
        ctx = {
            **await _detail_context(src, user, session),
            **await _capture_context(src, session),
            **context,
        }
        return _templates.TemplateResponse(
            request, "info_sources/detail.html", ctx, status_code=422
        )

    await set_capture_policy(session, src.info_source_id, policy)
    await session.commit()
    if not is_htmx:
        return RedirectResponse(url=f"/dashboard/info-sources/{source_id}", status_code=303)
    src = await _resolve_source(source_id, session)
    context = {**await _capture_policy_context(src, session), "swapped": True}
    response = _templates.TemplateResponse(
        request, "info_sources/_capture_policy_card.html", context
    )
    body = "Capture policy cleared." if policy is None else "Capture policy saved."
    response.headers["HX-Trigger"] = json.dumps({"showFlash": {"level": "success", "body": body}})
    return response


# ---------------------------------------------------------------------------
# GET /{source_id}/captures/{command_id}.png  (archiver#380 slice D, D4)
# ---------------------------------------------------------------------------

#: Content-addressed: the bytes behind a command's digest never change.
_IMAGE_CACHE = "private, max-age=31536000, immutable"


@router.get("/{source_id}/captures/{command_id}.png", response_model=None)
async def capture_image(
    source_id: str,
    command_id: str,
    request: Request,
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    """A stored capture's PNG, read from the captures bucket and served behind the login.

    404 while the switch is off, for an unknown or foreign command, for one
    whose image Archiver may not or cannot read (``capture_reader.image_uri``),
    with no reader, or on a failed read or hash check. A matching
    ``If-None-Match`` is a 304 without a read: the ETag is the digest.
    """
    _require_capture()
    src = await _resolve_source(source_id, session)
    command = await session.get(CaptureCommand, command_id)
    if command is None or command.info_source_id != src.info_source_id:
        raise DashboardNotFound("Capture not found")
    uri = image_uri(command, now=datetime.now(UTC))
    reader = capture_reader.bound()
    if uri is None or reader is None:
        raise DashboardNotFound("Capture image not available")
    etag = f'"{command.content_fingerprint}"'
    headers = {
        "Cache-Control": _IMAGE_CACHE,
        "ETag": etag,
        "X-Content-Type-Options": "nosniff",
    }
    if request.headers.get("If-None-Match") == etag:
        return Response(status_code=304, headers=headers)
    try:
        data = await read_capture(reader, uri, command.content_fingerprint)
    except CaptureUnavailable as e:
        raise DashboardNotFound("Capture image not available") from e
    return Response(content=data, media_type=IMAGE_MEDIA_TYPE, headers=headers)
