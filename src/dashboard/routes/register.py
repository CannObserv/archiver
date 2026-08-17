"""Dashboard — Information Item registration flow.

4-step wizard rendered by ``register/index.html``.  All four steps live in one
template; Alpine.js ``registerWizard`` manages client-side step navigation.
The final POST submits all fields atomically in a single transaction:
``get_or_create_domain`` (inside ``create_info_source``) + ``create_info_source``
+ ``InfoItem`` + ``InfoItemSource`` binding are all flushed before a single
``session.commit()``. That commit's announcement is the whole of the hand-off to
Watcher — there is no provisioning call (archiver#142).

HTMX partials:
  GET  /dashboard/register/url-check     — domain badge + Case A/B/C card
  GET  /dashboard/register/suggest-specs — sortableChips with full-spec values
  POST /dashboard/register/preview       — live extraction preview
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db_session
from src.core.models import InfoItem, InfoItemSource, InfoSource
from src.core.models.domain import Domain
from src.core.services.registry_announcement import announce_info_item
from src.core.tools.create_info_source import (
    InvalidSourceSpecError,
    InvalidUrlError,
    MixedAlgorithmFamilyError,
    create_info_source,
)
from src.core.tools.preview_extraction import preview_extraction
from src.core.url_canonicalization import canonicalize_url
from src.core.watch_spec_schema.validator import DEFAULT_WATCH_SPEC
from src.dashboard.cadence import CADENCE_LABELS, CADENCE_OPTIONS, DEFAULT_CADENCE
from src.dashboard.deps import get_dashboard_user

router = APIRouter(prefix="/dashboard/register")

_templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

# Expose the cadence vocabulary (#50) to every register template render so the
# dropdown options and default are rendered from a single source.
_templates.env.globals["cadence_labels"] = CADENCE_LABELS
_templates.env.globals["default_cadence"] = DEFAULT_CADENCE


# ---------------------------------------------------------------------------
# GET /dashboard/register  (step 1 landing)
# ---------------------------------------------------------------------------


@router.get("", response_class=HTMLResponse)
async def register_step1(
    request: Request,
    user=Depends(get_dashboard_user),
) -> HTMLResponse:
    """Step 1: URL input."""
    return _templates.TemplateResponse(request, "register/index.html", {"user": user, "errors": {}})


# ---------------------------------------------------------------------------
# GET /dashboard/register/url-check  (HTMX partial)
# ---------------------------------------------------------------------------


@router.get("/url-check", response_class=HTMLResponse)
async def url_check(
    request: Request,
    url: str = "",
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """HTMX partial: domain badge + Case A/B/C card for the given URL."""
    if not url:
        return HTMLResponse("")

    # Try to canonicalize; if it fails return an error partial
    try:
        canonical = canonicalize_url(url)
    except ValueError:
        return _templates.TemplateResponse(
            request,
            "register/_url_check.html",
            {"user": user, "error": "Invalid URL — must include scheme and host.", "url": url},
        )

    hostname = urlparse(canonical).hostname or ""

    # Look up the domain
    domain_row = (
        await session.execute(select(Domain).where(Domain.name == hostname))
    ).scalar_one_or_none()

    # Look up existing InfoSources at this URL
    src_rows = list(
        (await session.execute(select(InfoSource).where(InfoSource.url == canonical)))
        .scalars()
        .all()
    )

    # Check whether any source is bound to an active InfoItem
    bound_items = []
    if src_rows:
        source_ids = [s.info_source_id for s in src_rows]
        binding_rows = list(
            (
                await session.execute(
                    select(InfoItemSource).where(
                        InfoItemSource.info_source_id.in_(source_ids),
                        InfoItemSource.deactivated_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        if binding_rows:
            item_ids = list({b.info_item_id for b in binding_rows})
            item_rows = list(
                (await session.execute(select(InfoItem).where(InfoItem.info_item_id.in_(item_ids))))
                .scalars()
                .all()
            )
            bound_items = item_rows

    # Determine case
    if bound_items:
        case = "A"  # URL registered + bound
    elif src_rows:
        case = "B"  # URL exists but unbound
    else:
        case = "new"

    return _templates.TemplateResponse(
        request,
        "register/_url_check.html",
        {
            "user": user,
            "url": canonical,
            "hostname": hostname,
            "domain": domain_row,
            "case": case,
            "bound_items": bound_items,
            "existing_sources": src_rows,
            "error": None,
        },
    )


# ---------------------------------------------------------------------------
# GET /dashboard/register/suggest-specs  (HTMX partial)
# ---------------------------------------------------------------------------


@router.get("/suggest-specs", response_class=HTMLResponse)
async def suggest_specs(
    request: Request,
    url: str = "",
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """HTMX partial: top-5 selector suggestions from same domain as URL."""
    hostname = ""
    if url:
        try:
            canonical = canonicalize_url(url)
            hostname = urlparse(canonical).hostname or ""
        except ValueError:
            pass

    suggestions: list[dict] = []
    if hostname:
        src_rows = list(
            (
                await session.execute(
                    select(InfoSource).where(
                        InfoSource.domain_name == hostname,
                    )
                )
            )
            .scalars()
            .all()
        )
        # Count (algorithm, selector) combos; keep a representative spec for each.
        counter: Counter = Counter()
        spec_by_key: dict[tuple[str, str], dict] = {}
        for src in src_rows:
            for spec in src.source_specs or []:
                ext = spec.get("extraction", {})
                algo = ext.get("algorithm", "")
                selector = ext.get("selector", "") or ""
                key = (algo, selector)
                counter[key] += 1
                if key not in spec_by_key:
                    spec_by_key[key] = {
                        "schema_version": spec.get("schema_version", 1),
                        "extraction": ext,
                        "fingerprint": spec.get("fingerprint", {}),
                    }

        for (algo, selector), freq in counter.most_common(5):
            display = f"{algo}: {selector}" if selector else algo
            value = json.dumps([spec_by_key[(algo, selector)]])
            suggestions.append({"label": display, "frequency": freq, "value": value})

    return _templates.TemplateResponse(
        request,
        "register/_spec_suggestions.html",
        {"user": user, "suggestions": suggestions, "hostname": hostname},
    )


# ---------------------------------------------------------------------------
# POST /dashboard/register/preview  (HTMX partial)
# ---------------------------------------------------------------------------


@router.post("/preview", response_class=HTMLResponse)
async def preview(
    request: Request,
    url: str = Form(default=""),
    source_specs: str = Form(default=""),
    user=Depends(get_dashboard_user),
) -> HTMLResponse:
    """HTMX partial: attempt preview extraction and return result."""
    fetch_driver = getattr(request.app.state, "fetch_driver", None)
    if fetch_driver is None:
        return HTMLResponse(
            '<p class="text-muted">Preview unavailable — fetch driver not initialised.</p>'
        )

    try:
        canonical = canonicalize_url(url)
    except ValueError:
        return HTMLResponse('<p class="text-muted text-sm">Invalid URL.</p>')

    try:
        specs = json.loads(source_specs)
        if not isinstance(specs, list) or not specs:
            raise ValueError("empty")
        spec = specs[0]
    except (json.JSONDecodeError, ValueError):
        return HTMLResponse('<p class="text-muted text-sm">Invalid source_specs JSON.</p>')

    try:
        result = await preview_extraction(fetch_driver, canonical, spec)
        text_preview = "\n".join(c.text[:200] for c in result.chunks[:3] if c.text)[:500]
        suggested_name = result.page_title[:200]

        return _templates.TemplateResponse(
            request,
            "register/_preview_result.html",
            {
                "user": user,
                "text_preview": text_preview,
                "fingerprint": (result.computed_fingerprint or "")[:24],
                "errors": [],
                "suggested_name": suggested_name,
            },
        )
    except Exception as exc:  # noqa: BLE001
        return _templates.TemplateResponse(
            request,
            "register/_preview_result.html",
            {
                "user": user,
                "text_preview": "",
                "fingerprint": "",
                "errors": [str(exc)],
                "suggested_name": "",
            },
        )


# ---------------------------------------------------------------------------
# POST /dashboard/register  (atomic submit)
# ---------------------------------------------------------------------------


@router.post("")
async def register_submit(
    request: Request,
    url: str = Form(default=""),
    source_specs: str = Form(default=""),
    name: str = Form(default=""),
    description: str = Form(default=""),
    cadence: str = Form(default=""),
    watch_active: str = Form(default=""),
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Atomic: create_info_source → create InfoItem → bind → 303 to detail."""
    errors: dict[str, str] = {}

    # 1. Validate URL
    try:
        canonical_url = canonicalize_url(url)
    except ValueError as exc:
        errors["url"] = str(exc)
        return _templates.TemplateResponse(
            request,
            "register/index.html",
            {"user": user, "errors": errors, "url_value": url},
            status_code=422,
        )

    # 2. Parse source_specs
    try:
        specs = json.loads(source_specs) if source_specs.strip() else []
        if not isinstance(specs, list):
            raise ValueError("must be a JSON array")
    except (json.JSONDecodeError, ValueError) as exc:
        errors["source_specs"] = f"Invalid source_specs: {exc}"
        return _templates.TemplateResponse(
            request,
            "register/index.html",
            {
                "user": user,
                "errors": errors,
                "url_value": canonical_url,
                "source_specs_value": source_specs,
                "name_value": name,
                "description_value": description,
                "cadence_value": cadence,
                "watch_active_value": bool(watch_active),
                "initial_step": 2,
            },
            status_code=422,
        )

    # 3. Validate name
    if not name.strip():
        errors["name"] = "Name is required."
        return _templates.TemplateResponse(
            request,
            "register/index.html",
            {
                "user": user,
                "errors": errors,
                "url_value": canonical_url,
                "source_specs_value": source_specs,
                "name_value": name,
                "description_value": description,
                "cadence_value": cadence,
                "watch_active_value": bool(watch_active),
                "initial_step": 3,
            },
            status_code=422,
        )

    # 4. Atomic creation
    try:
        src = await create_info_source(session, url=canonical_url, source_specs=specs)
    except InvalidUrlError as exc:
        errors["url"] = str(exc)
        return _templates.TemplateResponse(
            request,
            "register/index.html",
            {"user": user, "errors": errors, "url_value": url},
            status_code=422,
        )
    except (InvalidSourceSpecError, MixedAlgorithmFamilyError) as exc:
        errors["source_specs"] = str(exc)
        return _templates.TemplateResponse(
            request,
            "register/index.html",
            {
                "user": user,
                "errors": errors,
                "url_value": canonical_url,
                "source_specs_value": source_specs,
                "name_value": name,
                "description_value": description,
                "cadence_value": cadence,
                "watch_active_value": bool(watch_active),
                "initial_step": 2,
            },
            status_code=422,
        )

    # Create InfoItem. Cadence and pause state are Archiver's own as of the
    # control-plane cutover (archiver#158): they are written here, *before* the
    # announcement, so the item's very first `info.registry` frame carries the
    # policy the operator actually chose — which, since archiver#142, is the only
    # frame there is. Registration no longer provisions anything over HTTP; the
    # announcement below *is* the registration as far as Watcher is concerned.
    owner_id = user.external_id if hasattr(user, "external_id") else None
    item = InfoItem(
        name=name.strip(),
        description=description.strip() or None,
        owner=owner_id,
        # Only a recognised selection becomes an interval. Anything else leaves
        # the column default standing, which spells "delegate to the consumer's
        # own default" — never fabricate a cadence the operator did not pick.
        watch_spec=(
            {"schema_version": 1, "interval": cadence}
            if cadence in CADENCE_OPTIONS
            else dict(DEFAULT_WATCH_SPEC)
        ),
        watch_active=bool(watch_active),
    )
    session.add(item)
    await session.flush()

    # Bind
    binding = InfoItemSource(
        info_item_id=item.info_item_id,
        info_source_id=src.info_source_id,
    )
    session.add(binding)
    await announce_info_item(session, item.info_item_id)
    await session.commit()
    await session.refresh(item)

    return RedirectResponse(url=f"/dashboard/info-items/{item.info_item_id}", status_code=303)
