"""Dashboard — Information Item registration flow.

4-step wizard (URL → Selector → Metadata → Review & Submit).
Steps 1–3 are client-side Alpine.js navigation; the final POST submits atomically.

HTMX partials:
  GET  /dashboard/register/url-check     — domain badge + Case A/B/C card
  GET  /dashboard/register/suggest-specs — sortableChips with selector suggestions
  POST /dashboard/register/preview       — preview extraction result
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
from src.core.tools.create_info_source import (
    InvalidSourceSpecError,
    InvalidUrlError,
    MixedAlgorithmFamilyError,
    create_info_source,
)
from src.core.url_canonicalization import canonicalize_url
from src.dashboard.deps import get_dashboard_user

router = APIRouter(prefix="/dashboard/register", tags=["dashboard-register"])

_templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


# ---------------------------------------------------------------------------
# GET /dashboard/register  (step 1 landing)
# ---------------------------------------------------------------------------


@router.get("", response_class=HTMLResponse)
async def register_step1(
    request: Request,
    user=Depends(get_dashboard_user),
) -> HTMLResponse:
    """Step 1: URL input."""
    return _templates.TemplateResponse(request, "register/step1.html", {"user": user, "errors": {}})


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
        # Extract (algorithm, selector) combos
        counter: Counter = Counter()
        for src in src_rows:
            for spec in src.source_specs or []:
                ext = spec.get("extraction", {})
                algo = ext.get("algorithm", "")
                selector = ext.get("selector", "")
                label = f"{algo}: {selector}" if selector else algo
                counter[label] += 1

        for label, freq in counter.most_common(5):
            suggestions.append({"label": label, "frequency": freq})

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
    fetcher = getattr(request.app.state, "http_fetcher", None)
    if fetcher is None:
        return HTMLResponse(
            '<p class="text-muted">Preview unavailable — HTTP fetcher not initialised.</p>'
        )

    try:
        canonical = canonicalize_url(url)
    except ValueError:
        return HTMLResponse('<p class="text-muted text-small">Invalid URL.</p>')

    try:
        specs = json.loads(source_specs)
        if not isinstance(specs, list) or not specs:
            raise ValueError("empty")
        spec = specs[0]
    except (json.JSONDecodeError, ValueError):
        return HTMLResponse('<p class="text-muted text-small">Invalid source_specs JSON.</p>')

    try:
        from src.core.tools.preview_extraction import preview_extraction

        result = await preview_extraction(canonical, spec, fetcher=fetcher)
        text_preview = "\n".join(c.text[:200] for c in result.chunks[:3] if c.text)[:500]
        suggested_name = ""
        for chunk in result.chunks:
            if chunk.chunk_type == "title" and chunk.text:
                suggested_name = chunk.text.strip()[:200]
                break

        return _templates.TemplateResponse(
            request,
            "register/_preview_result.html",
            {
                "user": user,
                "text_preview": text_preview,
                "fingerprint": result.fingerprint[:24] if result.fingerprint else "",
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
            "register/step1.html",
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
            "register/step1.html",
            {
                "user": user,
                "errors": errors,
                "url_value": canonical_url,
                "source_specs_value": source_specs,
                "name_value": name,
                "description_value": description,
                "initial_step": 2,
            },
            status_code=422,
        )

    # 3. Validate name
    if not name.strip():
        errors["name"] = "Name is required."
        return _templates.TemplateResponse(
            request,
            "register/step1.html",
            {
                "user": user,
                "errors": errors,
                "url_value": canonical_url,
                "source_specs_value": source_specs,
                "name_value": name,
                "description_value": description,
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
            "register/step1.html",
            {"user": user, "errors": errors, "url_value": url},
            status_code=422,
        )
    except (InvalidSourceSpecError, MixedAlgorithmFamilyError) as exc:
        errors["source_specs"] = str(exc)
        return _templates.TemplateResponse(
            request,
            "register/step1.html",
            {
                "user": user,
                "errors": errors,
                "url_value": canonical_url,
                "source_specs_value": source_specs,
                "name_value": name,
                "description_value": description,
                "initial_step": 2,
            },
            status_code=422,
        )

    # Create InfoItem
    owner_id = user.external_id if hasattr(user, "external_id") else None
    item = InfoItem(
        name=name.strip(),
        description=description.strip() or None,
        owner=owner_id,
    )
    session.add(item)
    await session.flush()

    # Bind
    from src.core.models.info_item_source import InfoItemSource as _IIS

    binding = _IIS(
        info_item_id=item.info_item_id,
        info_source_id=src.info_source_id,
    )
    session.add(binding)
    await session.commit()
    await session.refresh(item)

    return RedirectResponse(url=f"/dashboard/info-items/{item.info_item_id}", status_code=303)
