"""Dashboard — Information Item registration flow.

4-step wizard rendered by ``register/index.html``.  All four steps live in one
template; Alpine.js ``registerWizard`` manages client-side step navigation.
The final POST submits all fields atomically in a single transaction:
``get_or_create_domain`` (inside ``create_info_source``) + ``create_info_source``
+ ``InfoItem`` + ``InfoItemSource`` binding are all flushed before a single
``session.commit()``. That commit's announcement is the whole of the hand-off to
Watcher — there is no provisioning call (archiver#142).

Case B (sources at the URL, none bound) reuses one by default (archiver#51):
the operator's ``source_choice`` names it, its specs are saved through
``update_info_source_specs`` in place of ``create_info_source``, and the bind
refuses a source some item took since the check (409). ``source_choice=new``
keeps the create path.

HTMX partials:
  GET  /dashboard/register/url-check     — domain badge + Case A/B/C card
  GET  /dashboard/register/suggest-specs — sortableChips with full-spec values
  POST /dashboard/register/preview       — live extraction preview
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.api.deps import get_db_session
from src.core.models import InfoItem, InfoItemSource, InfoSource, SourceRevision
from src.core.models.domain import Domain
from src.core.services.registry_announcement import announce_info_item
from src.core.source_spec_schema.validator import validate_source_spec
from src.core.tools.bind_info_source import InfoSourceAlreadyBoundError, bind_info_source
from src.core.tools.create_info_source import (
    InvalidSourceSpecError,
    InvalidUrlError,
    MixedAlgorithmFamilyError,
    create_info_source,
)
from src.core.tools.preview_extraction import SourceSpecValidationError, preview_extraction
from src.core.tools.update_info_source_specs import (
    InvalidSourceSpecError as UpdateInvalidSpecError,
)
from src.core.tools.update_info_source_specs import (
    MixedAlgorithmFamilyError as UpdateMixedFamilyError,
)
from src.core.tools.update_info_source_specs import update_info_source_specs
from src.core.url_canonicalization import canonicalize_url, source_hostname
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

    check = await _check_url(session, canonical)
    # One reusable source is the default; with several, nothing is chosen for
    # the operator (archiver#51).
    candidates = check["candidates"]
    choice = str(candidates[0]["source"].info_source_id) if len(candidates) == 1 else ""
    return _templates.TemplateResponse(
        request,
        "register/_url_check.html",
        {"user": user, **_card(check, choice)},
    )


NEW_SOURCE = "new"


async def _check_url(session: AsyncSession, canonical: str) -> dict[str, Any]:
    """Classify a canonical URL: Case A (a source is bound), B (sources, none bound), new.

    The url-check card's context. Case B also lists each source as a reuse
    candidate (archiver#51): its revision count, a specs summary, and any
    errors the current schema finds in its stored specs (#164).
    """
    hostname = source_hostname(canonical) or ""
    domain_row = (
        await session.execute(select(Domain).where(Domain.name == hostname))
    ).scalar_one_or_none()
    src_rows = list(
        (
            await session.execute(
                select(InfoSource)
                .where(InfoSource.url == canonical)
                .order_by(InfoSource.info_source_id)
            )
        )
        .scalars()
        .all()
    )

    bound_items: list[InfoItem] = []
    candidates: list[dict[str, Any]] = []
    if src_rows:
        source_ids = [s.info_source_id for s in src_rows]
        item_ids = (
            await session.execute(
                select(InfoItemSource.info_item_id).where(
                    InfoItemSource.info_source_id.in_(source_ids),
                    InfoItemSource.deactivated_at.is_(None),
                )
            )
        ).scalars()
        bound_items = list(
            (
                await session.execute(
                    select(InfoItem).where(InfoItem.info_item_id.in_(set(item_ids)))
                )
            )
            .scalars()
            .all()
        )
        if not bound_items:
            counts = dict(
                (
                    await session.execute(
                        select(SourceRevision.info_source_id, func.count())
                        .where(SourceRevision.info_source_id.in_(source_ids))
                        .group_by(SourceRevision.info_source_id)
                    )
                ).all()
            )
            candidates = [_candidate(src, counts.get(src.info_source_id, 0)) for src in src_rows]

    if bound_items:
        case = "A"  # URL registered + bound
    elif src_rows:
        case = "B"  # URL exists but unbound
    else:
        case = "new"

    return {
        "url": canonical,
        "hostname": hostname,
        "domain": domain_row,
        "case": case,
        "bound_items": bound_items,
        "existing_sources": src_rows,
        "candidates": candidates,
        "error": None,
    }


def _card(check: dict[str, Any], choice: str) -> dict[str, Any]:
    """The card's context: *check*, the checked ``source_choice``, and the data island.

    The island carries each candidate's stored specs and revision count, so
    the wizard can pre-fill step 2 and the review without another request.
    """
    island: dict[str, Any] = {
        "hostname": check["hostname"],
        "case": check["case"],
        "domain_known": check["domain"] is not None,
    }
    if check["case"] == "B":
        island["source_choice"] = choice
        island["candidates"] = {
            str(c["source"].info_source_id): {"specs": c["specs_json"], "revisions": c["revisions"]}
            for c in check["candidates"]
        }
    return {**check, "source_choice": choice, "island": island}


def _candidate(src: InfoSource, revisions: int) -> dict[str, Any]:
    specs = list(src.source_specs or [])
    # A stored element may predate validation altogether (#164): report it, don't 500.
    errors: list[str] = []
    for i, spec in enumerate(specs):
        if not isinstance(spec, dict):
            errors.append(f"/source_specs/{i}: not an object")
            continue
        errors += [
            f"/source_specs/{i}{e['path']}: {e['message']}" for e in validate_source_spec(spec)[1]
        ]
    return {
        "source": src,
        "revisions": revisions,
        "summary": _specs_summary(specs),
        "specs_json": json.dumps(specs),
        "spec_errors": errors,
    }


def _specs_summary(specs: list[dict]) -> str:
    """The wizard's ``selectorSummary`` server-side: ``css: #a``, ``full_page``, ``2 specs (…)``."""
    extractions = [(s.get("extraction") or {}) if isinstance(s, dict) else {} for s in specs]
    algos = [e.get("algorithm", "?") for e in extractions]
    if len(specs) != 1:
        return f"{len(specs)} specs ({' + '.join(algos)})"
    selector = extractions[0].get("selector")
    return f"{algos[0]}: {selector}" if selector else algos[0]


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
            hostname = source_hostname(canonical) or ""
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
        # Count (algorithm, selector, ignore_selectors) combos; keep a representative
        # spec for each. ignore_selectors is in the key so a chip never carries
        # another spec's exclusions (#378).
        counter: Counter = Counter()
        spec_by_key: dict[tuple[str, str, tuple[str, ...]], dict] = {}
        for src in src_rows:
            for spec in src.source_specs or []:
                ext = spec.get("extraction", {})
                algo = ext.get("algorithm", "")
                selector = ext.get("selector", "") or ""
                key = (algo, selector, tuple(ext.get("ignore_selectors") or ()))
                counter[key] += 1
                if key not in spec_by_key:
                    spec_by_key[key] = {
                        "schema_version": spec.get("schema_version", 1),
                        "extraction": ext,
                        "fingerprint": spec.get("fingerprint", {}),
                    }

        for key, freq in counter.most_common(5):
            algo, selector, ignore = key
            display = f"{algo}: {selector}" if selector else algo
            if ignore:
                # As JSON: a selector may hold spaces or commas, and the chips key on the label.
                display += f", ignoring {json.dumps(list(ignore), ensure_ascii=False)}"
            value = json.dumps([spec_by_key[key]])
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
        # Zero chunks under a selector is a miss, not an empty page (#356): Processor
        # publishes it as an empty extraction rather than an error (processor#37). An
        # empty css selector is the whole page, so it has nothing to miss (CR 5).
        no_match = not result.chunks and bool(spec["extraction"].get("selector"))

        return _templates.TemplateResponse(
            request,
            "register/_preview_result.html",
            {
                "user": user,
                "text_preview": text_preview,
                "no_match": no_match,
                "fingerprint": (result.computed_fingerprint or "")[:24],
                "errors": [],
                "suggested_name": suggested_name,
            },
        )
    except Exception as exc:  # noqa: BLE001
        errors = (
            [f"{err['path']}: {err['message']}" for err in exc.errors]
            if isinstance(exc, SourceSpecValidationError)
            else [str(exc)]
        )
        return _templates.TemplateResponse(
            request,
            "register/_preview_result.html",
            {
                "user": user,
                "text_preview": "",
                "fingerprint": "",
                "errors": errors,
                "suggested_name": "",
            },
        )


# ---------------------------------------------------------------------------
# POST /dashboard/register  (atomic submit)
# ---------------------------------------------------------------------------


async def _rerender(
    request: Request,
    session: AsyncSession,
    user,
    *,
    status_code: int,
    step: int,
    errors: dict[str, str],
    url: str,
    form: dict[str, str],
) -> HTMLResponse:
    """Re-open the wizard at *step*, every field sticky, the url-check card included.

    htmx fetches the card only on the URL's ``change``, so without the include
    a re-render would drop the Case B choice the operator made (archiver#51).
    """
    context: dict[str, Any] = {
        "user": user,
        "errors": errors,
        "url_value": url,
        "source_specs_value": form["source_specs"],
        "name_value": form["name"],
        "description_value": form["description"],
        "cadence_value": form["cadence"],
        "watch_active_value": bool(form["watch_active"]),
        "initial_step": step,
    }
    try:
        canonical = canonicalize_url(url)
    except ValueError:
        canonical = None
    if canonical is not None:
        check = await _check_url(session, canonical)
        context |= {**_card(check, form["source_choice"]), "url_checked": True}
    return _templates.TemplateResponse(
        request, "register/index.html", context, status_code=status_code
    )


@router.post("")
async def register_submit(
    request: Request,
    url: str = Form(default=""),
    source_specs: str = Form(default=""),
    name: str = Form(default=""),
    description: str = Form(default=""),
    cadence: str = Form(default=""),
    watch_active: str = Form(default=""),
    source_choice: str = Form(default=""),
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Atomic: create (or, in Case B, reuse) the source → create InfoItem → bind → 303."""
    form = {
        "source_specs": source_specs,
        "name": name,
        "description": description,
        "cadence": cadence,
        "watch_active": watch_active,
        "source_choice": source_choice,
    }

    async def rerender(status_code: int, step: int, field: str, message: str, at: str = url):
        return await _rerender(
            request,
            session,
            user,
            status_code=status_code,
            step=step,
            errors={field: message},
            url=at,
            form=form,
        )

    # 1. Validate URL
    try:
        canonical_url = canonicalize_url(url)
    except ValueError as exc:
        return await rerender(422, 1, "url", str(exc))

    # 2. Parse source_specs
    try:
        specs = json.loads(source_specs) if source_specs.strip() else []
        if not isinstance(specs, list):
            raise ValueError("must be a JSON array")
    except (json.JSONDecodeError, ValueError) as exc:
        return await rerender(422, 2, "source_specs", f"Invalid source_specs: {exc}", canonical_url)

    # 3. Validate name
    if not name.strip():
        return await rerender(422, 3, "name", "Name is required.", canonical_url)

    # 4. Case B: which source? The server re-derives the case rather than trust
    # the card the client last saw (archiver#51).
    reuse: InfoSource | None = None
    if source_choice and source_choice != NEW_SOURCE:
        try:
            reuse = await session.get(InfoSource, ULID.from_str(source_choice))
        except ValueError:
            reuse = None
        if reuse is None or reuse.url != canonical_url:
            return await rerender(
                422,
                1,
                "source_choice",
                "The chosen Information Source is not at this URL.",
                canonical_url,
            )
    elif not source_choice and (await _check_url(session, canonical_url))["case"] == "B":
        return await rerender(
            422,
            1,
            "source_choice",
            "Choose an existing Information Source to reuse, or create a new one.",
            canonical_url,
        )

    # 5. Atomic creation
    if reuse is None:
        try:
            src = await create_info_source(session, url=canonical_url, source_specs=specs)
        except InvalidUrlError as exc:
            return await rerender(422, 1, "url", str(exc))
        except (InvalidSourceSpecError, MixedAlgorithmFamilyError) as exc:
            return await rerender(422, 2, "source_specs", str(exc), canonical_url)

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

    if reuse is None:
        session.add(item)
        await session.flush()
        # Bind: emits info_item_primary_changed (archiver#390). Both rows were
        # flushed above, so the tool's refusals cannot fire here.
        await bind_info_source(
            session, info_item_id=item.info_item_id, info_source_id=src.info_source_id
        )
    else:
        # A savepoint, so a refusal leaves no item behind. The source is
        # unbound, so its edited specs affect no other item; the bind locks it
        # and refuses one bound since the check (archiver#51).
        try:
            async with session.begin_nested():
                await update_info_source_specs(
                    session, info_source_id=reuse.info_source_id, source_specs=specs
                )
                session.add(item)
                await session.flush()
                await bind_info_source(
                    session,
                    info_item_id=item.info_item_id,
                    info_source_id=reuse.info_source_id,
                    require_unbound_source=True,
                )
        except (UpdateInvalidSpecError, UpdateMixedFamilyError) as exc:
            return await rerender(422, 2, "source_specs", str(exc), canonical_url)
        except InfoSourceAlreadyBoundError:
            return await rerender(
                409,
                1,
                "source_choice",
                "That Information Source was bound to another Information Item after the "
                "URL check (listed below). Submit again to create a new source at this URL.",
                canonical_url,
            )

    await announce_info_item(session, item.info_item_id)
    await session.commit()
    await session.refresh(item)

    return RedirectResponse(url=f"/dashboard/info-items/{item.info_item_id}", status_code=303)
